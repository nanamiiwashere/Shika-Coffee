import csv
from datetime import date
import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from psycopg2.extensions import connection as PgConnection

from app.database import get_raw_db as get_db
from app.schemas import ShiftNoteCreate, ShiftNoteUpdate
from app.security import get_current_user, require_role

router = APIRouter(
    prefix="/reports",
    tags=["Reports & Dashboard"],
    dependencies=[Depends(require_role("admin", "manager"))],
)


@router.get("/dashboard")
def dashboard_summary(
    tz_offset_minutes: int | None = Query(None, ge=-840, le=840),
    db: PgConnection = Depends(get_db),
):
    with db.cursor() as cur:
        if tz_offset_minutes is None:
            cur.execute(
                """
                SELECT
                    (SELECT COALESCE(SUM(total_amount), 0.00) FROM sales WHERE status = 'completed' AND transaction_date >= CURRENT_DATE) AS today_revenue,
                    (SELECT COUNT(*) FROM sales WHERE status = 'completed' AND transaction_date >= CURRENT_DATE) AS today_transactions,
                    (SELECT COUNT(*) FROM raw_materials WHERE current_stock <= minimum_stock) AS low_stock_count,
                    (SELECT COUNT(*) FROM products WHERE is_active = TRUE) AS active_products_count
                """
            )
        else:
            cur.execute(
                """
                WITH bounds AS (
                    SELECT (date_trunc('day', (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - (%s * INTERVAL '1 minute')) AT TIME ZONE 'UTC')
                           + (%s * INTERVAL '1 minute') AS day_start
                )
                SELECT
                    (SELECT COALESCE(SUM(total_amount), 0.00) FROM sales, bounds
                     WHERE status = 'completed' AND transaction_date >= bounds.day_start
                       AND transaction_date < bounds.day_start + INTERVAL '1 day') AS today_revenue,
                    (SELECT COUNT(*) FROM sales, bounds
                     WHERE status = 'completed' AND transaction_date >= bounds.day_start
                       AND transaction_date < bounds.day_start + INTERVAL '1 day') AS today_transactions,
                    (SELECT COUNT(*) FROM raw_materials WHERE current_stock <= minimum_stock) AS low_stock_count,
                    (SELECT COUNT(*) FROM products WHERE is_active = TRUE) AS active_products_count
                """,
                (tz_offset_minutes, tz_offset_minutes),
            )
        return cur.fetchone()


@router.get("/revenue")
def revenue_report(
    date_from: date,
    date_to: date,
    tz_offset_minutes: int | None = Query(None, ge=-840, le=840),
    db: PgConnection = Depends(get_db),
):
    with db.cursor() as cur:
        if tz_offset_minutes is None:
            cur.execute(
                """
                SELECT payment_method,
                       COUNT(id) AS total_transactions,
                       SUM(subtotal) AS gross_sales,
                       SUM(discount) AS total_discounts,
                       SUM(tax) AS total_tax,
                       SUM(total_amount) AS net_revenue
                FROM sales
                WHERE status = 'completed'
                  AND transaction_date >= %s
                  AND transaction_date < (%s::DATE + INTERVAL '1 day')
                GROUP BY payment_method
                ORDER BY net_revenue DESC
                """,
                (date_from, date_to),
            )
        else:
            cur.execute(
                """
                SELECT payment_method,
                       COUNT(id) AS total_transactions,
                       SUM(subtotal) AS gross_sales,
                       SUM(discount) AS total_discounts,
                       SUM(tax) AS total_tax,
                       SUM(total_amount) AS net_revenue
                FROM sales
                WHERE status = 'completed'
                  AND transaction_date >= ((%s::TIMESTAMP AT TIME ZONE 'UTC') + (%s * INTERVAL '1 minute'))
                  AND transaction_date < (((%s::DATE + INTERVAL '1 day')::TIMESTAMP AT TIME ZONE 'UTC') + (%s * INTERVAL '1 minute'))
                GROUP BY payment_method
                ORDER BY net_revenue DESC
                """,
                (date_from, tz_offset_minutes, date_to, tz_offset_minutes),
            )
        return cur.fetchall()


@router.get("/top-products")
def top_products(
    days: int = Query(30, ge=1, le=3650),
    date_from: date | None = None,
    date_to: date | None = None,
    tz_offset_minutes: int | None = Query(None, ge=-840, le=840),
    db: PgConnection = Depends(get_db),
):
    with db.cursor() as cur:
        if date_from and date_to:
            if tz_offset_minutes is None:
                date_clause = "AND s.transaction_date >= %s AND s.transaction_date < (%s::DATE + INTERVAL '1 day')"
                params: tuple[Any, ...] = (date_from, date_to)
            else:
                date_clause = (
                    "AND s.transaction_date >= ((%s::TIMESTAMP AT TIME ZONE 'UTC') + (%s * INTERVAL '1 minute')) "
                    "AND s.transaction_date < (((%s::DATE + INTERVAL '1 day')::TIMESTAMP AT TIME ZONE 'UTC') + (%s * INTERVAL '1 minute'))"
                )
                params = (date_from, tz_offset_minutes, date_to, tz_offset_minutes)
        else:
            date_clause = "AND s.transaction_date >= CURRENT_DATE - (%s * INTERVAL '1 day')"
            params = (days,)
        cur.execute(
            f"""
            SELECT p.id AS product_id, p.sku, p.name AS product_name, p.image_url, c.name AS category_name,
                   SUM(si.quantity) AS units_sold,
                   SUM(si.subtotal) AS total_sales_volume
            FROM sale_items si
            JOIN products p ON si.product_id = p.id
            JOIN categories c ON p.category_id = c.id
            JOIN sales s ON si.sale_id = s.id
            WHERE s.status = 'completed'
              {date_clause}
            GROUP BY p.id, p.sku, p.name, p.image_url, c.name
            ORDER BY units_sold DESC
            LIMIT 10
            """,
            params,
        )
        return cur.fetchall()


@router.get("/cogs")
def cogs_margin_report(db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            """
            WITH product_cogs AS (
                SELECT pr.product_id,
                       SUM(pr.quantity_required * rm.latest_purchase_price) AS calculated_cogs
                FROM product_recipes pr
                JOIN raw_materials rm ON pr.raw_material_id = rm.id
                GROUP BY pr.product_id
            )
            SELECT p.id AS product_id, p.sku, p.name AS product_name, p.price AS selling_price,
                   (pc.product_id IS NOT NULL) AS has_recipe,
                   COALESCE(pc.calculated_cogs, 0.00) AS estimated_cogs,
                   (p.price - COALESCE(pc.calculated_cogs, 0.00)) AS gross_profit,
                   ROUND(((p.price - COALESCE(pc.calculated_cogs, 0.00)) / NULLIF(p.price, 0)) * 100, 2) AS margin_percentage
            FROM products p
            LEFT JOIN product_cogs pc ON p.id = pc.product_id
            WHERE p.is_active = TRUE
            ORDER BY gross_profit DESC
            """
        )
        return cur.fetchall()


def _csv_cell(value: Any) -> Any:
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


@router.get("/analytics/export")
def export_analytics_csv(
    date_from: date,
    date_to: date,
    tz_offset_minutes: int | None = Query(None, ge=-840, le=840),
    db: PgConnection = Depends(get_db),
):
    rev_rows = revenue_report(date_from=date_from, date_to=date_to, tz_offset_minutes=tz_offset_minutes, db=db)
    top_rows = top_products(date_from=date_from, date_to=date_to, tz_offset_minutes=tz_offset_minutes, db=db)
    cogs_rows = cogs_margin_report(db=db)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Shika Coffee Analytics Report", f"{date_from} to {date_to}"])
    writer.writerow([])
    writer.writerow([
        "Section",
        "Label",
        "SKU / Method",
        "Transactions / Qty",
        "Gross / Price",
        "Discounts / COGS",
        "Tax / Profit",
        "Net / Margin %",
    ])
    for r in rev_rows:
        writer.writerow([
            "Revenue",
            _csv_cell(str(r["payment_method"]).upper()),
            _csv_cell(r["payment_method"]),
            r["total_transactions"],
            r["gross_sales"],
            r["total_discounts"],
            r["total_tax"],
            r["net_revenue"],
        ])
    for t in top_rows:
        writer.writerow([
            "Top Product",
            _csv_cell(t["product_name"]),
            _csv_cell(t["sku"]),
            t["units_sold"],
            "",
            "",
            "",
            t["total_sales_volume"],
        ])
    for c in cogs_rows:
        writer.writerow([
            "Product Margin",
            _csv_cell(c["product_name"]),
            _csv_cell(c["sku"]),
            "Has Recipe" if c["has_recipe"] else "No Recipe",
            c["selling_price"],
            c["estimated_cogs"],
            c["gross_profit"],
            c["margin_percentage"],
        ])

    filename = f"shika-analytics-{date_from}-to-{date_to}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/shift-notes")
def list_shift_notes(
    limit: int = Query(50, ge=1, le=200),
    db: PgConnection = Depends(get_db),
):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT sn.id, sn.user_id, sn.category, sn.content, sn.is_done,
                   sn.created_at, sn.updated_at,
                   COALESCE(u.full_name, 'Staff') AS author_name
            FROM shift_notes sn
            LEFT JOIN users u ON sn.user_id = u.id
            ORDER BY sn.created_at DESC, sn.id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


@router.post("/shift-notes", status_code=status.HTTP_201_CREATED)
def create_shift_note(
    body: ShiftNoteCreate,
    user: dict[str, Any] = Depends(get_current_user),
    db: PgConnection = Depends(get_db),
):
    with db, db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO shift_notes (user_id, category, content)
            VALUES (%s, %s, %s)
            RETURNING id, user_id, category, content, is_done, created_at, updated_at
            """,
            (user["id"], body.category, body.content),
        )
        row = dict(cur.fetchone())
    row["author_name"] = user.get("full_name") or "Staff"
    return row


@router.patch("/shift-notes/{note_id}")
def update_shift_note(
    note_id: int,
    body: ShiftNoteUpdate,
    db: PgConnection = Depends(get_db),
):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    set_clause = ", ".join(f"{col} = %s" for col in fields)
    with db, db.cursor() as cur:
        cur.execute(
            f"""
            UPDATE shift_notes
            SET {set_clause}, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id, user_id, category, content, is_done, created_at, updated_at
            """,
            (*fields.values(), note_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Shift note not found")
        result = dict(row)
        cur.execute("SELECT full_name FROM users WHERE id = %s", (result["user_id"],))
        author = cur.fetchone()
    result["author_name"] = author["full_name"] if author else "Staff"
    return result


@router.delete("/shift-notes/{note_id}")
def delete_shift_note(note_id: int, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute("DELETE FROM shift_notes WHERE id = %s RETURNING id", (note_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Shift note not found")
    return {"deleted_id": row["id"]}