from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from psycopg2.extras import RealDictCursor

from app.main import app

ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = ROOT / "migrations" / "002_seed_coffee_menu.sql"
REFERENCE_COFFEES = {
    "Americano": Decimal("4.50"),
    "Cappuccino": Decimal("5.00"),
    "Espresso": Decimal("4.00"),
    "Flat White": Decimal("5.50"),
    "Forest Cold Brew": Decimal("5.50"),
    "Iced Coffee Milk": Decimal("5.00"),
    "Mocha": Decimal("6.00"),
    "Nokotan Latte": Decimal("6.50"),
}
client = TestClient(app)


def apply_seed(db):
    with db, db.cursor() as cur:
        cur.execute(SEED_PATH.read_text(encoding="utf-8"))


def test_coffee_seed_populates_public_showcase_with_local_photos(seeded_db):
    apply_seed(seeded_db)

    response = client.get("/menu/products")
    assert response.status_code == 200
    coffees = [row for row in response.json() if row["category_name"] == "Coffee"]
    assert {row["name"]: Decimal(str(row["price"])) for row in coffees} == REFERENCE_COFFEES
    for coffee in coffees:
        assert set(coffee) == {"id", "name", "price", "image_url", "category_name"}
        assert coffee["image_url"].startswith("/static/images/menu/")
        asset = ROOT / "app" / coffee["image_url"].lstrip("/")
        assert asset.is_file()
        image = client.get(coffee["image_url"])
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/")


def test_coffee_seed_is_repeatable_without_duplicate_categories_or_products(seeded_db):
    apply_seed(seeded_db)
    apply_seed(seeded_db)

    with seeded_db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) AS count FROM categories WHERE LOWER(name) = 'coffee'")
        assert cur.fetchone()["count"] == 1
        cur.execute("SELECT COUNT(*) AS count FROM products WHERE sku LIKE 'COF-%'")
        assert cur.fetchone()["count"] == 8
        cur.execute("SELECT COUNT(*) AS count FROM products")
        assert cur.fetchone()["count"] == 9  # The existing fixture's Latte is preserved.


def test_coffee_seed_preserves_existing_product_details_and_inactive_status(seeded_db):
    with seeded_db, seeded_db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO products (category_id, sku, name, price, image_url, is_active)
            VALUES (1, 'CUSTOM-AMER', 'americano', 7.25, '/custom.jpg', FALSE)
            RETURNING id
            """
        )
        product_id = cur.fetchone()["id"]

    apply_seed(seeded_db)
    with seeded_db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM products WHERE LOWER(name) = 'americano'")
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == product_id
    assert rows[0]["sku"] == "CUSTOM-AMER"
    assert rows[0]["price"] == Decimal("7.25")
    assert rows[0]["category_id"] == 1
    assert rows[0]["image_url"] == "/custom.jpg"
    assert rows[0]["is_active"] is False


def test_public_visitors_can_browse_seeded_coffees_but_cannot_purchase(seeded_db):
    apply_seed(seeded_db)
    coffee = next(row for row in client.get("/menu/products").json() if row["name"] == "Americano")
    response = client.post(
        "/sales",
        json={
            "payment_method": "cash",
            "amount_paid": "10.00",
            "items": [{"product_id": coffee["id"], "quantity": 1}],
        },
    )
    assert response.status_code == 401
    assert client.post("/menu/products", json={}).status_code == 405
    with seeded_db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) AS count FROM sales")
        assert cur.fetchone()["count"] == 0
