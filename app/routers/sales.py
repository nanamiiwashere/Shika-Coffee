from collections import defaultdict
from datetime import date
from decimal import Decimal
import os
import socket
from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from psycopg2.extensions import connection as PgConnection

from app.database import get_raw_db as get_db
from app.qris import cancel_qris_session, create_qris_session, get_qris_session, pay_qris_session, render_qr_svg
from app.schemas import OrderStatus, OrderStatusUpdate, PaymentMethod, QrisSessionCreate, SaleCreate
from app.security import get_current_user, require_role
from app.uploads import resolve_rows_images

router = APIRouter(prefix="/sales", tags=["POS Sales"])


def _qris_public_base(request: Request) -> str:
    override = os.getenv("QRIS_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if override:
        return override
    host = request.url.hostname or ""
    if host in ("127.0.0.1", "localhost"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                lan_ip = s.getsockname()[0]
            if lan_ip and not lan_ip.startswith("127."):
                port = f":{request.url.port}" if request.url.port else ""
                return f"{request.url.scheme}://{lan_ip}{port}"
        except OSError:
            pass
    return str(request.base_url).rstrip("/")


@router.post("/qris/sessions", status_code=201)
def start_qris_session(
    body: QrisSessionCreate,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(get_current_user),
    db: PgConnection = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    session = create_qris_session(
        db=db,
        amount=body.amount,
        customer_name=body.customer_name,
        user_id=user["id"],
        timeout_seconds=body.timeout_seconds,
    )
    pay_url = f"{_qris_public_base(request)}{session['pay_path']}"
    session["pay_url"] = pay_url
    session["qr_svg"] = render_qr_svg(pay_url)
    return session


@router.get("/qris/sessions/{session_id}")
def read_qris_session(session_id: str, response: Response, db: PgConnection = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return get_qris_session(db, session_id)


@router.post("/qris/sessions/{session_id}/pay")
def confirm_qris_session(session_id: str, response: Response, db: PgConnection = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return pay_qris_session(db, session_id)


@router.post("/qris/sessions/{session_id}/cancel")
def abort_qris_session(
    session_id: str,
    response: Response,
    _: dict[str, Any] = Depends(get_current_user),
    db: PgConnection = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    return cancel_qris_session(db, session_id)


@router.post("", status_code=201)
def create_sale(
    body: SaleCreate,
    user: dict[str, Any] = Depends(get_current_user),
    db: PgConnection = Depends(get_db),
):
    qty_by_product: dict[int, int] = defaultdict(int)
    for item in body.items:
        qty_by_product[item.product_id] += item.quantity
    product_ids = sorted(qty_by_product.keys())

    with db, db.cursor() as cur:
        cur.execute("SELECT id, name, price, is_active FROM products WHERE id = ANY(%s)", (product_ids,))
        products = {row["id"]: row for row in cur.fetchall()}
        for pid in product_ids:
            prod = products.get(pid)
            if not prod or not prod["is_active"]:
                raise HTTPException(status_code=400, detail=f"Product {pid} is missing or inactive")

        subtotal = sum(
            (products[item.product_id]["price"] * item.quantity for item in body.items),
            Decimal("0.00"),
        )
        total_amount = subtotal - body.discount + body.tax
        if total_amount < Decimal("0.00"):
            raise HTTPException(status_code=400, detail="Discount cannot exceed subtotal + tax")
        if body.amount_paid < total_amount:
            raise HTTPException(status_code=400, detail="Insufficient amount paid")
        change_amount = body.amount_paid - total_amount

        cur.execute(
            "SELECT product_id, raw_material_id, quantity_required FROM product_recipes WHERE product_id = ANY(%s)",
            (product_ids,),
        )
        required_by_material: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
        for rec in cur.fetchall():
            required_by_material[rec["raw_material_id"]] += (
                rec["quantity_required"] * qty_by_product[rec["product_id"]]
            )

        locked_materials: dict[int, dict[str, Any]] = {}
        if required_by_material:
            sorted_mat_ids = sorted(required_by_material.keys())
            cur.execute(
                "SELECT id, name, current_stock FROM raw_materials WHERE id = ANY(%s) ORDER BY id ASC FOR UPDATE",
                (sorted_mat_ids,),
            )
            locked_materials = {row["id"]: row for row in cur.fetchall()}
            for mat_id, needed in required_by_material.items():
                mat = locked_materials[mat_id]
                if mat["current_stock"] < needed:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Insufficient stock for {mat['name']} (available: {mat['current_stock']}, needed: {needed})",
                    )

        cur.execute(
            """
            INSERT INTO sales (
                invoice_number, user_id, customer_name, order_type,
                subtotal, discount, tax, total_amount, payment_method, amount_paid, change_amount
            )
            VALUES (
                'INV-' || TO_CHAR(CURRENT_DATE, 'YYYYMMDD') || '-' || LPAD(nextval('invoice_number_seq')::TEXT, 4, '0'),
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                user["id"],
                body.customer_name,
                body.order_type,
                subtotal,
                body.discount,
                body.tax,
                total_amount,
                body.payment_method,
                body.amount_paid,
                change_amount,
            ),
        )
        sale = cur.fetchone()

        for item in body.items:
            unit_price = products[item.product_id]["price"]
            cur.execute(
                """
                INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, subtotal, note)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (sale["id"], item.product_id, item.quantity, unit_price, unit_price * item.quantity, item.notes),
            )

        for mat_id in sorted(required_by_material.keys()):
            needed = required_by_material[mat_id]
            stock_before = locked_materials[mat_id]["current_stock"]
            stock_after = stock_before - needed
            cur.execute(
                "UPDATE raw_materials SET current_stock = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (stock_after, mat_id),
            )
            cur.execute(
                """
                INSERT INTO stock_mutations (
                    raw_material_id, mutation_type, quantity, stock_before, stock_after,
                    reference_type, reference_id, notes
                )
                VALUES (%s, 'out', %s, %s, %s, 'sale', %s, %s)
                """,
                (mat_id, needed, stock_before, stock_after, sale["id"], f"Sale {sale['invoice_number']}"),
            )

    return sale


@router.get("")
def list_sales(
    date_from: date | None = None,
    date_to: date | None = None,
    tz_offset_minutes: int | None = Query(None, ge=-840, le=840),
    status: Literal["completed", "cancelled"] | None = None,
    order_status: OrderStatus | None = None,
    user_id: int | None = None,
    payment_method: PaymentMethod | None = None,
    include_items: bool = False,
    _: dict[str, Any] = Depends(get_current_user),
    db: PgConnection = Depends(get_db),
):
    clauses, params = [], []
    if date_from:
        if tz_offset_minutes is None:
            clauses.append("s.transaction_date >= %s")
            params.append(date_from)
        else:
            clauses.append("s.transaction_date >= ((%s::TIMESTAMP AT TIME ZONE 'UTC') + (%s * INTERVAL '1 minute'))")
            params.extend([date_from, tz_offset_minutes])
    if date_to:
        if tz_offset_minutes is None:
            clauses.append("s.transaction_date < (%s::DATE + INTERVAL '1 day')")
            params.append(date_to)
        else:
            clauses.append("s.transaction_date < (((%s::DATE + INTERVAL '1 day')::TIMESTAMP AT TIME ZONE 'UTC') + (%s * INTERVAL '1 minute'))")
            params.extend([date_to, tz_offset_minutes])
    if status:
        clauses.append("s.status = %s")
        params.append(status)
    if order_status:
        clauses.append("s.order_status = %s")
        params.append(order_status)
    if user_id:
        clauses.append("s.user_id = %s")
        params.append(user_id)
    if payment_method:
        clauses.append("s.payment_method = %s")
        params.append(payment_method)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    # ponytail: capped at 1000 rows for bounded analytics queries; switch to SQL bucket aggregation if daily volume exceeds 1000 tickets.
    row_limit = 1000 if (date_from or date_to) else 200
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT s.*, u.full_name AS cashier_name
            FROM sales s
            JOIN users u ON u.id = s.user_id
            {where}
            ORDER BY s.transaction_date DESC
            LIMIT {row_limit}
            """,
            params,
        )
        rows = cur.fetchall()
        if not include_items or not rows:
            return rows

        sale_ids = [row["id"] for row in rows]
        cur.execute(
            """
            SELECT si.id, si.sale_id, si.product_id, si.quantity, si.unit_price, si.subtotal,
                   si.note AS notes, p.sku, p.name AS product_name, p.image_url
            FROM sale_items si
            JOIN products p ON p.id = si.product_id
            WHERE si.sale_id = ANY(%s)
            ORDER BY si.id ASC
            """,
            (sale_ids,),
        )
        items_by_sale: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in resolve_rows_images(cur.fetchall(), "image_url"):
            items_by_sale[item["sale_id"]].append(item)
        return [{**row, "items": items_by_sale[row["id"]]} for row in rows]


@router.get("/summary/today")
def get_today_sales_summary(
    _: dict[str, Any] = Depends(get_current_user),
    db: PgConnection = Depends(get_db),
):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS order_count
            FROM sales
            WHERE status = 'completed'
              AND transaction_date >= CURRENT_DATE
              AND transaction_date < CURRENT_DATE + INTERVAL '1 day'
            """
        )
        return cur.fetchone()


@router.get("/{sale_id}")
def get_sale(sale_id: int, _: dict[str, Any] = Depends(get_current_user), db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT s.*, u.full_name AS cashier_name FROM sales s JOIN users u ON u.id = s.user_id WHERE s.id = %s",
            (sale_id,),
        )
        sale = cur.fetchone()
        if not sale:
            raise HTTPException(status_code=404, detail="Sale not found")
        cur.execute(
            """
            SELECT si.id, si.sale_id, si.product_id, si.quantity, si.unit_price, si.subtotal,
                   si.note AS notes, p.sku, p.name AS product_name
            FROM sale_items si
            JOIN products p ON p.id = si.product_id
            WHERE si.sale_id = %s
            ORDER BY si.id ASC
            """,
            (sale_id,),
        )
        items = cur.fetchall()
    return {**sale, "items": items}


@router.post("/{sale_id}/cancel", dependencies=[Depends(require_role("admin", "manager"))])
def cancel_sale(sale_id: int, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute("SELECT * FROM sales WHERE id = %s FOR UPDATE", (sale_id,))
        sale = cur.fetchone()
        if not sale:
            raise HTTPException(status_code=404, detail="Sale not found")
        if sale["status"] == "cancelled":
            raise HTTPException(status_code=409, detail="Sale already cancelled")

        cur.execute(
            """
            SELECT raw_material_id, SUM(quantity) AS restore_qty
            FROM stock_mutations
            WHERE reference_type = 'sale' AND reference_id = %s AND mutation_type = 'out'
            GROUP BY raw_material_id
            ORDER BY raw_material_id ASC
            """,
            (sale_id,),
        )
        muts = cur.fetchall()

        if muts:
            mat_ids = [m["raw_material_id"] for m in muts]
            cur.execute(
                "SELECT id, current_stock FROM raw_materials WHERE id = ANY(%s) ORDER BY id ASC FOR UPDATE",
                (mat_ids,),
            )
            locked = {row["id"]: row for row in cur.fetchall()}
            for m in muts:
                mat_id = m["raw_material_id"]
                restore_qty = m["restore_qty"]
                stock_before = locked[mat_id]["current_stock"]
                stock_after = stock_before + restore_qty
                cur.execute(
                    "UPDATE raw_materials SET current_stock = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (stock_after, mat_id),
                )
                cur.execute(
                    """
                    INSERT INTO stock_mutations (
                        raw_material_id, mutation_type, quantity, stock_before, stock_after,
                        reference_type, reference_id, notes
                    )
                    VALUES (%s, 'in', %s, %s, %s, 'sale_cancel', %s, %s)
                    """,
                    (mat_id, restore_qty, stock_before, stock_after, sale_id, f"Cancelled {sale['invoice_number']}"),
                )

        cur.execute("UPDATE sales SET status = 'cancelled' WHERE id = %s RETURNING *", (sale_id,))
        return cur.fetchone()


@router.patch("/{sale_id}/order-status")
def update_order_status(
    sale_id: int,
    body: OrderStatusUpdate,
    _: dict[str, Any] = Depends(get_current_user),
    db: PgConnection = Depends(get_db),
):
    with db, db.cursor() as cur:
        cur.execute("SELECT * FROM sales WHERE id = %s FOR UPDATE", (sale_id,))
        sale = cur.fetchone()
        if not sale:
            raise HTTPException(status_code=404, detail="Sale not found")
        if sale["status"] == "cancelled":
            raise HTTPException(status_code=409, detail="Cannot update order status of a cancelled sale")
        cur.execute(
            "UPDATE sales SET order_status = %s WHERE id = %s RETURNING *",
            (body.order_status, sale_id),
        )
        return cur.fetchone()


@router.get("/{sale_id}/receipt")
def get_receipt(sale_id: int, user: dict[str, Any] = Depends(get_current_user), db: PgConnection = Depends(get_db)):
    data = get_sale(sale_id, user, db)
    return {
        "store_name": "Shika Coffee",
        "invoice_number": data["invoice_number"],
        "transaction_date": data["transaction_date"],
        "cashier": data["cashier_name"],
        "customer_name": data["customer_name"],
        "order_type": data["order_type"],
        "status": data["status"],
        "order_status": data.get("order_status", "received"),
        "items": [
            {
                "name": i["product_name"],
                "qty": i["quantity"],
                "unit_price": i["unit_price"],
                "subtotal": i["subtotal"],
                "notes": i["notes"],
            }
            for i in data["items"]
        ],
        "subtotal": data["subtotal"],
        "discount": data["discount"],
        "tax": data["tax"],
        "total_amount": data["total_amount"],
        "payment_method": data["payment_method"],
        "amount_paid": data["amount_paid"],
        "change_amount": data["change_amount"],
    }