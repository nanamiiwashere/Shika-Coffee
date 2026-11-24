from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.database import get_db, get_raw_db
from app.main import app
from app.security import get_current_user

client = TestClient(app)
MENU_FIELDS = {"id", "name", "price", "image_url", "category_name"}


@pytest.fixture
def no_db_client(monkeypatch):
    def unexpected_db():
        pytest.fail("This request must not access the database")

    monkeypatch.setitem(app.dependency_overrides, get_db, unexpected_db)
    monkeypatch.setitem(app.dependency_overrides, get_raw_db, unexpected_db)
    return TestClient(app)


@pytest.mark.parametrize("path", ["/products", "/sales/summary/today"])
def test_private_ui_endpoints_require_auth_without_db(no_db_client, path):
    res = no_db_client.get(path)
    assert res.status_code == 401


def test_public_menu_empty_without_db(no_db_client, monkeypatch):
    db = MagicMock()
    cur = db.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    monkeypatch.setitem(app.dependency_overrides, get_raw_db, lambda: db)

    res = no_db_client.get("/menu/products")
    assert res.status_code == 200
    assert res.json() == []
    cur.execute.assert_called_once()
    db.commit.assert_not_called()


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_public_menu_is_read_only_without_db(no_db_client, method):
    res = no_db_client.request(method, "/menu/products", json={})
    assert res.status_code == 405


@pytest.mark.parametrize("order_count", [0, 257])
def test_sales_summary_response_without_db(no_db_client, monkeypatch, order_count):
    db = MagicMock()
    cur = db.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = {"order_count": order_count}
    monkeypatch.setitem(app.dependency_overrides, get_raw_db, lambda: db)
    monkeypatch.setitem(
        app.dependency_overrides, get_current_user, lambda: {"id": 1, "role": "cashier"}
    )

    res = no_db_client.get("/sales/summary/today")
    assert res.status_code == 200
    assert res.json() == {"order_count": order_count}
    cur.execute.assert_called_once()


def test_public_menu_projection_active_filter_and_order(seeded_db):
    with seeded_db, seeded_db.cursor() as cur:
        cur.execute(
            """
            UPDATE products SET image_url = '/static/latte.jpg' WHERE id = 1;
            INSERT INTO categories (name) VALUES ('Tea');
            INSERT INTO products (category_id, sku, name, price, is_active) VALUES
              (1, 'MNU-ZULU', 'Zulu Coffee', 20000, TRUE),
              (1, 'MNU-AMER', 'Americano', 18000, TRUE),
              (2, 'MNU-TEA', 'Apple Tea', 15000, TRUE),
              (1, 'MNU-HIDDEN', 'Hidden Product', 5000, FALSE);
            """
        )

    res = client.get("/menu/products?active_only=false")
    assert res.status_code == 200
    rows = res.json()
    assert [(row["category_name"], row["name"]) for row in rows] == [
        ("Espresso Based", "Americano"),
        ("Espresso Based", "Latte"),
        ("Espresso Based", "Zulu Coffee"),
        ("Tea", "Apple Tea"),
    ]
    assert all(set(row) == MENU_FIELDS for row in rows)
    latte = next(row for row in rows if row["id"] == 1)
    assert Decimal(str(latte["price"])) == Decimal("25000.00")
    assert latte["image_url"] == "/static/latte.jpg"
    assert rows[0]["image_url"] is None


@pytest.mark.parametrize(
    "beans_stock,milk_stock,is_low_stock",
    [
        (100, 500, False),
        (10, 500, True),
        (9, 500, True),
        (17, 500, True),
        (18, 150, False),
        (100, 50, True),
        (100, 149, True),
        (10, 50, True),
    ],
)
def test_products_low_stock_thresholds(
    seeded_db, cashier_headers, beans_stock, milk_stock, is_low_stock
):
    with seeded_db, seeded_db.cursor() as cur:
        cur.execute("UPDATE raw_materials SET current_stock = %s WHERE id = 1", (beans_stock,))
        cur.execute("UPDATE raw_materials SET current_stock = %s WHERE id = 2", (milk_stock,))

    res = client.get("/products", headers=cashier_headers)
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["is_low_stock"] is is_low_stock
    assert set(rows[0]) == {
        "id", "category_id", "sku", "name", "price", "is_active",
        "created_at", "updated_at", "image_url", "category_name", "is_low_stock",
    }


def test_products_without_recipe_are_not_low_stock(seeded_db, cashier_headers):
    with seeded_db, seeded_db.cursor() as cur:
        cur.execute(
            """
            UPDATE raw_materials SET current_stock = 10 WHERE id = 1;
            INSERT INTO products (category_id, sku, name, price)
            VALUES (1, 'MNU-NO-RECIPE', 'No Recipe', 10000);
            """
        )

    res = client.get("/products", headers=cashier_headers)
    assert res.status_code == 200
    assert {row["name"]: row["is_low_stock"] for row in res.json()} == {
        "Latte": True,
        "No Recipe": False,
    }


def test_products_preserve_filters_and_name_order(seeded_db, cashier_headers):
    with seeded_db, seeded_db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO categories (name) VALUES ('Tea');
            INSERT INTO products (category_id, sku, name, price, is_active) VALUES
              (1, 'MNU-AMER', 'Americano', 18000, TRUE),
              (1, 'MNU-HIDDEN', 'Hidden Product', 5000, FALSE),
              (2, 'MNU-TEA', 'Apple Tea', 15000, TRUE);
            """
        )

    for params, expected_names in [
        ({}, ["Americano", "Apple Tea", "Latte"]),
        ({"active_only": "false"}, ["Americano", "Apple Tea", "Hidden Product", "Latte"]),
        ({"category_id": 1}, ["Americano", "Latte"]),
        ({"search": "lAtT"}, ["Latte"]),
        ({"search": "mnu-amer"}, ["Americano"]),
        ({"search": "hidden"}, []),
        ({"search": "hidden", "active_only": "false", "category_id": 1}, ["Hidden Product"]),
        ({"search": "tea", "category_id": 1}, []),
    ]:
        res = client.get("/products", params=params, headers=cashier_headers)
        assert res.status_code == 200
        assert [row["name"] for row in res.json()] == expected_names
        assert all(isinstance(row["is_low_stock"], bool) for row in res.json())


def test_sales_summary_today_empty(seeded_db, cashier_headers):
    res = client.get("/sales/summary/today", headers=cashier_headers)
    assert res.status_code == 200
    assert res.json() == {"order_count": 0}


def test_sales_summary_today_counts_completed_in_local_day_uncapped(seeded_db, cashier_headers):
    with seeded_db, seeded_db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sales (
                invoice_number, user_id, subtotal, total_amount,
                payment_method, amount_paid, status, transaction_date
            )
            SELECT 'UI-TODAY-' || n, 2, 25000, 25000,
                   'cash', 25000, 'completed', CURRENT_DATE + INTERVAL '12 hours'
            FROM generate_series(1, 205) AS n;

            INSERT INTO sales (
                invoice_number, user_id, subtotal, total_amount,
                payment_method, amount_paid, status, transaction_date
            ) VALUES
              ('UI-START', 1, 25000, 25000, 'cash', 25000, 'completed', CURRENT_DATE),
              ('UI-END', 1, 25000, 25000, 'cash', 25000, 'completed',
               CURRENT_DATE + INTERVAL '1 day' - INTERVAL '1 microsecond'),
              ('UI-YESTERDAY', 1, 25000, 25000, 'cash', 25000, 'completed',
               CURRENT_DATE - INTERVAL '1 microsecond'),
              ('UI-TOMORROW', 1, 25000, 25000, 'cash', 25000, 'completed',
               CURRENT_DATE + INTERVAL '1 day'),
              ('UI-CANCELLED', 1, 25000, 25000, 'cash', 25000, 'cancelled',
               CURRENT_DATE + INTERVAL '12 hours');
            """
        )

    res = client.get("/sales/summary/today", headers=cashier_headers)
    assert res.status_code == 200
    assert res.json() == {"order_count": 207}
