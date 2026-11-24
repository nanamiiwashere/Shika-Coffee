from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PgConnection

from app.database import get_raw_db as get_db
from app.schemas import (
    CategoryCreate,
    CategoryUpdate,
    ImageUploadRequest,
    ProductCreate,
    ProductUpdate,
    RawMaterialCreate,
    RawMaterialUpdate,
    RecipeItemCreate,
    RecipeItemUpdate,
    SupplierCreate,
    SupplierUpdate,
    UnitCreate,
    UnitUpdate,
)
from app.security import get_current_user, require_role
from app.uploads import is_allowed_image_url, remove_local_upload, resolve_row_images, resolve_rows_images, save_local_image

router = APIRouter(tags=["Master Data"])
ADMIN_OR_MGR = [Depends(require_role("admin", "manager"))]
AUTHENTICATED = [Depends(get_current_user)]


def _build_update(fields: dict) -> tuple[str, list]:
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    return ", ".join(f"{col} = %s" for col in fields), list(fields.values())


def _clean_local_image_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if not is_allowed_image_url(cleaned):
        raise HTTPException(status_code=422, detail="Image must be uploaded locally")
    return cleaned


# --- Categories ---
@router.get("/categories", dependencies=AUTHENTICATED)
def list_categories(db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM categories ORDER BY name")
        return cur.fetchall()


@router.post("/categories", status_code=201, dependencies=ADMIN_OR_MGR)
def create_category(body: CategoryCreate, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute(
            "INSERT INTO categories (name, description) VALUES (%s, %s) RETURNING *",
            (body.name, body.description),
        )
        return cur.fetchone()


@router.patch("/categories/{category_id}", dependencies=ADMIN_OR_MGR)
def update_category(category_id: int, body: CategoryUpdate, db: PgConnection = Depends(get_db)):
    set_clause, vals = _build_update(body.model_dump(exclude_none=True))
    with db, db.cursor() as cur:
        cur.execute(f"UPDATE categories SET {set_clause} WHERE id = %s RETURNING *", (*vals, category_id))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Category not found")
    return row


@router.delete("/categories/{category_id}", status_code=204, dependencies=ADMIN_OR_MGR)
def delete_category(category_id: int, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute("DELETE FROM categories WHERE id = %s", (category_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Category not found")


# --- Public Menu ---
@router.get("/menu/products")
def list_menu_products(db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT p.id, p.name, p.price, p.image_url, c.name AS category_name
            FROM products p
            JOIN categories c ON c.id = p.category_id
            WHERE p.is_active = TRUE
            ORDER BY c.name, p.name
            """
        )
        return resolve_rows_images(cur.fetchall(), "image_url")


# --- Products (Soft-delete only) ---
@router.get("/products", dependencies=AUTHENTICATED)
def list_products(
    search: str | None = None,
    category_id: int | None = None,
    active_only: bool = True,
    db: PgConnection = Depends(get_db),
):
    clauses, params = [], []
    if active_only:
        clauses.append("p.is_active = TRUE")
    if category_id is not None:
        clauses.append("p.category_id = %s")
        params.append(category_id)
    if search:
        clauses.append("(p.name ILIKE %s OR p.sku ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT p.*, c.name AS category_name,
                   EXISTS (
                       SELECT 1
                       FROM product_recipes pr
                       JOIN raw_materials rm ON rm.id = pr.raw_material_id
                       WHERE pr.product_id = p.id
                         AND (rm.current_stock <= rm.minimum_stock
                              OR rm.current_stock < pr.quantity_required)
                   ) AS is_low_stock
            FROM products p
            JOIN categories c ON c.id = p.category_id
            {where}
            ORDER BY p.name
            """,
            params,
        )
        return resolve_rows_images(cur.fetchall(), "image_url")


@router.get("/products/{product_id}", dependencies=AUTHENTICATED)
def get_product(product_id: int, db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT p.*, c.name AS category_name FROM products p JOIN categories c ON c.id = p.category_id WHERE p.id = %s",
            (product_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    return resolve_row_images(row, "image_url")


@router.post("/products/upload-image", dependencies=ADMIN_OR_MGR)
def upload_product_image(body: ImageUploadRequest):
    return {"image_url": save_local_image(body.image_data, "products", "prod")}


@router.post("/products", status_code=201, dependencies=ADMIN_OR_MGR)
def create_product(body: ProductCreate, db: PgConnection = Depends(get_db)):
    image_url = _clean_local_image_url(body.image_url)
    with db, db.cursor() as cur:
        cur.execute(
            "INSERT INTO products (category_id, sku, name, price, image_url) VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (body.category_id, body.sku, body.name, body.price, image_url),
        )
        return cur.fetchone()


@router.patch("/products/{product_id}", dependencies=ADMIN_OR_MGR)
def update_product(product_id: int, body: ProductUpdate, db: PgConnection = Depends(get_db)):
    raw = body.model_dump(exclude_unset=True)
    fields = {k: v for k, v in raw.items() if k != "image_url" and v is not None}
    old_image: str | None = None
    if "image_url" in raw:
        fields["image_url"] = _clean_local_image_url(raw["image_url"])
    set_clause, vals = _build_update(fields)
    with db, db.cursor() as cur:
        if "image_url" in fields:
            cur.execute("SELECT image_url FROM products WHERE id = %s", (product_id,))
            existing = cur.fetchone()
            old_image = existing["image_url"] if existing else None
        cur.execute(
            f"UPDATE products SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING *",
            (*vals, product_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    if old_image and old_image != row.get("image_url"):
        remove_local_upload(old_image, "products")
    return row


@router.delete("/products/{product_id}", dependencies=ADMIN_OR_MGR)
def deactivate_product(product_id: int, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute(
            "UPDATE products SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING id, sku, name, is_active",
            (product_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    return row


# --- Units ---
@router.get("/units", dependencies=AUTHENTICATED)
def list_units(db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM units ORDER BY id")
        return cur.fetchall()


@router.post("/units", status_code=201, dependencies=ADMIN_OR_MGR)
def create_unit(body: UnitCreate, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute("INSERT INTO units (name, symbol) VALUES (%s, %s) RETURNING *", (body.name, body.symbol))
        return cur.fetchone()


@router.patch("/units/{unit_id}", dependencies=ADMIN_OR_MGR)
def update_unit(unit_id: int, body: UnitUpdate, db: PgConnection = Depends(get_db)):
    set_clause, vals = _build_update(body.model_dump(exclude_none=True))
    with db, db.cursor() as cur:
        cur.execute(f"UPDATE units SET {set_clause} WHERE id = %s RETURNING *", (*vals, unit_id))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Unit not found")
    return row


@router.delete("/units/{unit_id}", status_code=204, dependencies=ADMIN_OR_MGR)
def delete_unit(unit_id: int, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute("DELETE FROM units WHERE id = %s", (unit_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Unit not found")


# --- Raw Materials (current_stock cannot be edited directly) ---
@router.get("/raw-materials", dependencies=AUTHENTICATED)
def list_raw_materials(db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT rm.*, u.symbol AS unit_symbol
            FROM raw_materials rm
            JOIN units u ON u.id = rm.unit_id
            ORDER BY rm.name
            """
        )
        return resolve_rows_images(cur.fetchall(), "image_url")


@router.get("/raw-materials/{material_id}", dependencies=AUTHENTICATED)
def get_raw_material(material_id: int, db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT rm.*, u.symbol AS unit_symbol FROM raw_materials rm JOIN units u ON u.id = rm.unit_id WHERE rm.id = %s",
            (material_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Raw material not found")
    return resolve_row_images(row, "image_url")


@router.post("/raw-materials/upload-image", dependencies=ADMIN_OR_MGR)
def upload_raw_material_image(body: ImageUploadRequest):
    return {"image_url": save_local_image(body.image_data, "roastery", "lot")}


@router.post("/raw-materials", status_code=201, dependencies=ADMIN_OR_MGR)
def create_raw_material(body: RawMaterialCreate, db: PgConnection = Depends(get_db)):
    image_url = _clean_local_image_url(body.image_url)
    with db, db.cursor() as cur:
        cur.execute(
            """
            WITH ins AS (
                INSERT INTO raw_materials (unit_id, sku, name, minimum_stock, image_url)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            )
            SELECT ins.*, u.symbol AS unit_symbol
            FROM ins
            JOIN units u ON u.id = ins.unit_id
            """,
            (body.unit_id, body.sku, body.name, body.minimum_stock, image_url),
        )
        return cur.fetchone()


@router.patch("/raw-materials/{material_id}", dependencies=ADMIN_OR_MGR)
def update_raw_material(material_id: int, body: RawMaterialUpdate, db: PgConnection = Depends(get_db)):
    raw = body.model_dump(exclude_unset=True)
    fields = {k: v for k, v in raw.items() if k != "image_url" and v is not None}
    old_image: str | None = None
    if "image_url" in raw:
        fields["image_url"] = _clean_local_image_url(raw["image_url"])
    set_clause, vals = _build_update(fields)
    with db, db.cursor() as cur:
        if "image_url" in fields:
            cur.execute("SELECT image_url FROM raw_materials WHERE id = %s", (material_id,))
            existing = cur.fetchone()
            old_image = existing["image_url"] if existing else None
        cur.execute(
            f"""
            WITH upd AS (
                UPDATE raw_materials
                SET {set_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING *
            )
            SELECT upd.*, u.symbol AS unit_symbol
            FROM upd
            JOIN units u ON u.id = upd.unit_id
            """,
            (*vals, material_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Raw material not found")
    if old_image and old_image != row.get("image_url"):
        remove_local_upload(old_image, "roastery")
    return row


# --- Suppliers ---
@router.get("/suppliers", dependencies=AUTHENTICATED)
def list_suppliers(db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM suppliers ORDER BY name")
        return cur.fetchall()


@router.get("/suppliers/{supplier_id}", dependencies=AUTHENTICATED)
def get_supplier(supplier_id: int, db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM suppliers WHERE id = %s", (supplier_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return row


@router.post("/suppliers", status_code=201, dependencies=ADMIN_OR_MGR)
def create_supplier(body: SupplierCreate, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute(
            "INSERT INTO suppliers (name, phone, email, address) VALUES (%s, %s, %s, %s) RETURNING *",
            (body.name, body.phone, body.email, body.address),
        )
        return cur.fetchone()


@router.patch("/suppliers/{supplier_id}", dependencies=ADMIN_OR_MGR)
def update_supplier(supplier_id: int, body: SupplierUpdate, db: PgConnection = Depends(get_db)):
    set_clause, vals = _build_update(body.model_dump(exclude_none=True))
    with db, db.cursor() as cur:
        cur.execute(f"UPDATE suppliers SET {set_clause} WHERE id = %s RETURNING *", (*vals, supplier_id))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return row


@router.delete("/suppliers/{supplier_id}", status_code=204, dependencies=ADMIN_OR_MGR)
def delete_supplier(supplier_id: int, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute("DELETE FROM suppliers WHERE id = %s", (supplier_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Supplier not found")


# --- Product Recipes (BOM) ---
@router.get("/products/{product_id}/recipes", dependencies=AUTHENTICATED)
def get_product_recipe(product_id: int, db: PgConnection = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT pr.id, pr.product_id, pr.raw_material_id, rm.sku, rm.name AS material_name,
                   pr.quantity_required, u.symbol AS unit_symbol
            FROM product_recipes pr
            JOIN raw_materials rm ON rm.id = pr.raw_material_id
            JOIN units u ON u.id = rm.unit_id
            WHERE pr.product_id = %s
            ORDER BY rm.name
            """,
            (product_id,),
        )
        return cur.fetchall()


@router.post("/products/{product_id}/recipes", status_code=201, dependencies=ADMIN_OR_MGR)
def add_recipe_item(product_id: int, body: RecipeItemCreate, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO product_recipes (product_id, raw_material_id, quantity_required)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (product_id, body.raw_material_id, body.quantity_required),
        )
        return cur.fetchone()


@router.put("/products/{product_id}/recipes/{raw_material_id}", dependencies=ADMIN_OR_MGR)
def update_recipe_item(
    product_id: int,
    raw_material_id: int,
    body: RecipeItemUpdate,
    db: PgConnection = Depends(get_db),
):
    with db, db.cursor() as cur:
        cur.execute(
            """
            UPDATE product_recipes
            SET quantity_required = %s
            WHERE product_id = %s AND raw_material_id = %s
            RETURNING *
            """,
            (body.quantity_required, product_id, raw_material_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Recipe item not found")
    return row


@router.delete("/products/{product_id}/recipes/{raw_material_id}", status_code=204, dependencies=ADMIN_OR_MGR)
def delete_recipe_item(product_id: int, raw_material_id: int, db: PgConnection = Depends(get_db)):
    with db, db.cursor() as cur:
        cur.execute(
            "DELETE FROM product_recipes WHERE product_id = %s AND raw_material_id = %s",
            (product_id, raw_material_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Recipe item not found")