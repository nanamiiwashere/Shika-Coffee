import os
from pathlib import Path

from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "migrations" / "001_schema.sql"


def _resolve_test_db_url() -> str:
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        env_file = REPO_ROOT / ".env"
        if env_file.is_file():
            for raw_line in env_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if line and not line.startswith("#") and line.startswith("DATABASE_URL="):
                    raw_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        raw_url = raw_url or os.environ["DATABASE_URL"]
        url = make_url(raw_url).set(database="shika_coffee_test")
    else:
        url = make_url(raw_url)

    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg2")
    return url.render_as_string(hide_password=False)


os.environ["DATABASE_URL"] = _resolve_test_db_url()
os.environ.setdefault("JWT_SECRET", "test-secret-key-at-least-32-bytes-long")

import pytest
from app.database import engine
from app.security import create_access_token, hash_password


@pytest.fixture
def seeded_db():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    pw = hash_password("password123")

    raw_conn = engine.raw_connection()
    conn = raw_conn.driver_connection
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            row = cur.fetchone()
            db_name = row["current_database"] if isinstance(row, dict) else row[0]
            assert db_name == "shika_coffee_test", f"Refusing to truncate non-test DB: {db_name}"
            cur.execute(schema_sql)
            cur.execute(
                """
                TRUNCATE user_oauth_accounts, users, categories, products, units, suppliers,
                         raw_materials, product_recipes, sales, sale_items,
                         material_purchases, material_purchase_items, stock_mutations,
                         shift_notes
                RESTART IDENTITY CASCADE;
                ALTER SEQUENCE invoice_number_seq RESTART WITH 1;
                ALTER SEQUENCE po_number_seq RESTART WITH 1;
                """
            )
            cur.execute(
                """
                INSERT INTO users (email, username, password_hash, full_name, role, is_active) VALUES
                  ('cashier@shika.test', 'cashier1', %s, 'Cashier Test', 'cashier', TRUE),
                  ('manager@shika.test', 'manager1', %s, 'Manager Test', 'manager', TRUE),
                  ('admin@shika.test',   'admin1',   %s, 'Admin Test',   'admin',   TRUE);
                INSERT INTO categories (name) VALUES ('Espresso Based');
                INSERT INTO products (category_id, sku, name, price) VALUES (1, 'MNU-LATTE', 'Latte', 25000.00);
                INSERT INTO units (name, symbol) VALUES ('Gram', 'gr'), ('Milliliter', 'ml');
                INSERT INTO suppliers (name, phone) VALUES ('Roastery Nusantara', '08123456789');
                INSERT INTO raw_materials (unit_id, sku, name, current_stock, minimum_stock, latest_purchase_price) VALUES
                  (1, 'RAW-BEANS', 'Espresso Beans', 100.00, 10.00, 200.00),
                  (2, 'RAW-MILK',  'Fresh Milk',     500.00, 50.00,  20.00);
                INSERT INTO product_recipes (product_id, raw_material_id, quantity_required) VALUES
                  (1, 1, 18.00),
                  (1, 2, 150.00);
                """,
                (pw, pw, pw),
            )
        yield conn
    finally:
        raw_conn.close()
        engine.dispose()


@pytest.fixture
def cashier_headers():
    return {"Authorization": f"Bearer {create_access_token(user_id=1, role='cashier')}"}


@pytest.fixture
def manager_headers():
    return {"Authorization": f"Bearer {create_access_token(user_id=2, role='manager')}"}


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {create_access_token(user_id=3, role='admin')}"}
