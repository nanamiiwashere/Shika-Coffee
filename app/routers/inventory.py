from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PgConnection

from app.database import get_raw_db as get_db
from app.schemas import PurchaseCreate, StockAdjustmentIn, StockWasteIn
from app.security import get_current_user, require_role

router = APIRouter(tags=["Purchases & Inventory"])
ADMIN_OR_MGR = [Depends(require_role("admin", "manager"))]
AUTHENTICATED = [Depends(get_current_user)]


@router.post("/purchases", status_code=201)
def create_purchase(
    body: PurchaseCreate,
    user: dict[str, Any] = Depends(require_role("admin", "manager")),
    db: PgConnection = Depends(get_db),
):
    subtotals = [(i.quantity * i.unit_price).quantize(Decimal("0.01")) for i in body.items]
    total_cost = sum(subtotals, Decimal("0.00"))
    mat_ids = sorted({i.raw_material_id for i in body.items})

    with db, db.cursor() as cur:
        cur.execute(
            "SELECT id, current_stock FROM raw_materials WHERE id = ANY(%s) ORDER BY id ASC FOR UPDATE",
            (mat_ids,),
        )
        locked = {row["id"]: row for row in cur.fetchall()}
        if len(locked) != len(mat_ids):
            raise HTTPException(status_code=400, detail="One or more raw materials do not exist")

        cur.execute(
            """
            INSERT INTO material_purchases (po_number, supplier_id, user_id, total_cost, notes)
            VALUES (
                'PO-' || TO_CHAR(CURRENT_DATE, 'YYYYMM') || '-' || LPAD(nextval('po_number_seq')::TEXT, 4, '0'),
                %s, %s, %s, %s
            )
            RETURNING *
            """,
            (body.supplier_id, user["id"], total_cost, body.notes),
        )
        po = cur.fetchone()

        running_stock = {mid: locked[mid]["current_stock"] for mid in mat_ids}
        for item, subtotal in zip(body.items, subtotals):
            cur.execute(
                """
                INSERT INTO material_purchase_items (purchase_id, raw_material_id, quantity, unit_price, subtotal)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (po["id"], item.raw_material_id, item.quantity, item.unit_price, subtotal),
            )
            stock_before = running_stock[item.raw_material_id]
            stock_after = stock_before + item.quantity
            running_stock[item.raw_material_id] = stock_after

            cur.execute(
                """
                UPDATE raw_materials
                SET current_stock = %s, latest_purchase_price = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (stock_after, item.unit_price, item.raw_material_id),
            )
            cur.execute(
                """
                INSERT INTO stock_mutations (
                    raw_material_id, mutation_type, quantity, stock_before, stock_after,
                    reference_type, reference_id, notes
                )
                VALUES (%s, 'in', %s, %s, %s, 'purchase', %s, %s)
                """,
                (item.raw_material_id, item.quantity, stock_before, stock_after, po["id"], f"PO {po['po_number']}"),
            )

    return po


@router.get("/purchases", dependencies=ADMIN_OR_MGR)
def list_purchases(db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT mp.*, s.name AS supplier_name, u.full_name AS created_by
            FROM material_purchases mp
            JOIN suppliers s ON s.id = mp.supplier_id
            JOIN users u ON u.id = mp.user_id
            ORDER BY mp.created_at DESC
            LIMIT 200
            """
        )
        return cur.fetchall()


@router.get("/purchases/summary", dependencies=ADMIN_OR_MGR)
def get_purchases_summary(db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM material_purchases) AS total_orders,
                (SELECT COALESCE(SUM(total_cost), 0.00) FROM material_purchases) AS total_spend,
                (SELECT COUNT(*) FROM suppliers) AS active_suppliers
            """
        )
        return cur.fetchone()


@router.get("/purchases/{purchase_id}", dependencies=ADMIN_OR_MGR)
def get_purchase(purchase_id: int, db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT mp.*, s.name AS supplier_name FROM material_purchases mp JOIN suppliers s ON s.id = mp.supplier_id WHERE mp.id = %s",
            (purchase_id,),
        )
        po = cur.fetchone()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        cur.execute(
            """
            SELECT mpi.*, rm.sku, rm.name AS material_name
            FROM material_purchase_items mpi
            JOIN raw_materials rm ON rm.id = mpi.raw_material_id
            WHERE mpi.purchase_id = %s
            """,
            (purchase_id,),
        )
        items = cur.fetchall()
    return {**po, "items": items}


@router.get("/inventory", dependencies=AUTHENTICATED)
def get_inventory(db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT rm.*, u.symbol AS unit_symbol,
                   (rm.current_stock <= rm.minimum_stock) AS is_low_stock
            FROM raw_materials rm
            JOIN units u ON u.id = rm.unit_id
            ORDER BY is_low_stock DESC, rm.name ASC
            """
        )
        return cur.fetchall()


@router.get("/inventory/low-stock", dependencies=AUTHENTICATED)
def get_low_stock(db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT rm.id, rm.sku, rm.name, rm.current_stock, rm.minimum_stock,
                   u.symbol AS unit_symbol,
                   (rm.minimum_stock - rm.current_stock) AS reorder_deficit,
                   rm.latest_purchase_price
            FROM raw_materials rm
            JOIN units u ON u.id = rm.unit_id
            WHERE rm.current_stock <= rm.minimum_stock
            ORDER BY (rm.current_stock / NULLIF(rm.minimum_stock, 0)) ASC
            """
        )
        return cur.fetchall()


@router.post("/inventory/adjustment", dependencies=ADMIN_OR_MGR)
def adjust_stock(body: StockAdjustmentIn, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute("SELECT id, current_stock FROM raw_materials WHERE id = %s FOR UPDATE", (body.raw_material_id,))
        mat = cur.fetchone()
        if not mat:
            raise HTTPException(status_code=404, detail="Raw material not found")

        stock_before = mat["current_stock"]
        diff = body.actual_stock - stock_before
        if diff == Decimal("0.00"):
            raise HTTPException(status_code=400, detail="Actual stock matches current stock; no adjustment needed")

        cur.execute(
            "UPDATE raw_materials SET current_stock = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (body.actual_stock, body.raw_material_id),
        )
        cur.execute(
            """
            INSERT INTO stock_mutations (
                raw_material_id, mutation_type, quantity, stock_before, stock_after,
                reference_type, notes
            )
            VALUES (%s, 'adjustment', %s, %s, %s, 'adjustment', %s)
            RETURNING *
            """,
            (body.raw_material_id, abs(diff), stock_before, body.actual_stock, body.notes),
        )
        return cur.fetchone()


@router.post("/inventory/waste", dependencies=AUTHENTICATED)
def record_waste(body: StockWasteIn, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute(
            "SELECT id, name, current_stock FROM raw_materials WHERE id = %s FOR UPDATE",
            (body.raw_material_id,),
        )
        mat = cur.fetchone()
        if not mat:
            raise HTTPException(status_code=404, detail="Raw material not found")
        if mat["current_stock"] < body.quantity:
            raise HTTPException(status_code=409, detail=f"Insufficient stock for waste entry on {mat['name']}")

        stock_before = mat["current_stock"]
        stock_after = stock_before - body.quantity
        cur.execute(
            "UPDATE raw_materials SET current_stock = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (stock_after, body.raw_material_id),
        )
        cur.execute(
            """
            INSERT INTO stock_mutations (
                raw_material_id, mutation_type, quantity, stock_before, stock_after,
                reference_type, notes
            )
            VALUES (%s, 'waste', %s, %s, %s, 'waste', %s)
            RETURNING *
            """,
            (body.raw_material_id, body.quantity, stock_before, stock_after, body.notes),
        )
        return cur.fetchone()


@router.get("/inventory/{material_id}/mutations", dependencies=AUTHENTICATED)
def get_material_mutations(material_id: int, db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM stock_mutations
            WHERE raw_material_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT 200
            """,
            (material_id,),
        )
        return cur.fetchall()