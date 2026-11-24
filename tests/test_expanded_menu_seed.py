from collections import Counter
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree

from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_SEED = ROOT / "migrations" / "002_seed_coffee_menu.sql"
EXPANDED_SEED = ROOT / "migrations" / "003_seed_expanded_menu.sql"
EXPECTED_MENU = {
    "Coffee": {
        "Kyoto Cold Brew": 30000,
        "Tokyo Vanilla Latte": 32000,
        "Hojicha Espresso Latte": 35000,
        "Kinako Latte": 34000,
        "Kuromitsu Latte": 34000,
        "Okinawa Brown Sugar Coffee": 33000,
        "Uji Matcha Espresso": 38000,
        "Black Sesame Latte": 36000,
        "Yuzu Espresso Tonic": 35000,
        "Osaka Honey Coffee": 30000,
        "Salted Caramel Latte": 34000,
        "Hazelnut Latte": 32000,
        "Coconut Latte": 32000,
        "Hokkaido White Mocha": 37000,
        "Dark Chocolate Mocha": 35000,
        "Cinnamon Cappuccino": 30000,
        "Piccolo": 25000,
        "Cortado": 26000,
        "Long Black": 24000,
        "Espresso Macchiato": 23000,
    },
    "Beverages": {
        "Uji Matcha Latte": 32000,
        "Kyoto Hojicha Latte": 30000,
        "Kinako Milk": 28000,
        "Kuromitsu Milk": 28000,
        "Yuzu Citrus Soda": 27000,
        "Sakura Lemon Tea": 26000,
        "Peach Oolong Tea": 25000,
        "Iced Genmaicha": 22000,
        "Hokkaido Chocolate Milk": 30000,
        "Ichigo Strawberry Milk": 30000,
    },
    "Snacks": {
        "Azuki Dorayaki": 22000,
        "Matcha White Chocolate Cookie": 18000,
        "Kinako Mochi": 24000,
        "Hojicha Roll Cake": 28000,
        "Kuromitsu Milk Pudding": 25000,
    },
    "Bites": {
        "Shio Onigiri": 18000,
        "Tuna Mayo Onigiri": 24000,
        "Tamago Sando": 30000,
        "Shoyu Chicken Karaage": 35000,
        "Nori Fries": 25000,
    },
}
ILLUSTRATIONS = {
    "Beverages": "/static/images/menu/shika-expanded-beverages.svg",
    "Snacks": "/static/images/menu/shika-expanded-snacks.svg",
    "Bites": "/static/images/menu/shika-expanded-bites.svg",
}
COFFEE_PHOTOS = {
    "americano.jpg", "cappuccino.jpg", "espresso.jpg", "flat-white.jpg",
    "forest-cold-brew.jpg", "iced-coffee-milk.jpg", "mocha.jpg", "nokotan-latte.jpg",
}


def apply_seed(db, path):
    with db, db.cursor() as cur:
        cur.execute(path.read_text(encoding="utf-8"))


def snapshot(db, table):
    # Callers only select these fixed tables; never interpolate external input.
    assert table in {"products", "categories"}
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {table} ORDER BY id")
        return {row["id"]: dict(row) for row in cur.fetchall()}


def test_expansion_adds_exactly_40_correctly_categorized_rupiah_items(seeded_db):
    apply_seed(seeded_db, ORIGINAL_SEED)
    before = snapshot(seeded_db, "products")
    apply_seed(seeded_db, EXPANDED_SEED)
    after = snapshot(seeded_db, "products")

    assert len(before) == 9  # Eight reference coffees plus the fixture's Latte.
    assert len(after) == 49
    assert {key: after[key] for key in before} == before
    added_ids = set(after) - set(before)
    assert len(added_ids) == 40

    with seeded_db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT p.*, c.name AS category_name
            FROM products p JOIN categories c ON c.id = p.category_id
            WHERE p.id = ANY(%s)
            """,
            (list(added_ids),),
        )
        added = cur.fetchall()
        cur.execute(
            """
            SELECT c.name, COUNT(*) AS count FROM products p
            JOIN categories c ON c.id = p.category_id
            WHERE c.name IN ('Coffee', 'Beverages', 'Snacks', 'Bites')
            GROUP BY c.name
            """
        )
        assert {row["name"]: row["count"] for row in cur.fetchall()} == {
            "Coffee": 28, "Beverages": 10, "Snacks": 5, "Bites": 5,
        }

    assert Counter(row["category_name"] for row in added) == {
        "Coffee": 20, "Beverages": 10, "Snacks": 5, "Bites": 5,
    }
    assert {row["name"] for row in added} == {
        name for items in EXPECTED_MENU.values() for name in items
    }
    assert len({row["sku"] for row in added}) == 40
    assert not {row["name"].lower() for row in added} & {
        row["name"].lower() for row in before.values()
    }
    for row in added:
        category = row["category_name"]
        assert row["price"] == Decimal(EXPECTED_MENU[category][row["name"]])
        assert row["price"] == row["price"].to_integral_value()
        low, high = (18000, 45000) if category in {"Coffee", "Beverages"} else (12000, 40000)
        assert low <= row["price"] <= high
        assert row["is_active"] is True
        assert row["image_url"].startswith("/static/images/menu/")
        asset = ROOT / "app" / row["image_url"].lstrip("/")
        assert asset.is_file()
        if category == "Coffee":
            assert asset.name in COFFEE_PHOTOS
        else:
            assert row["image_url"] == ILLUSTRATIONS[category]


def test_expanded_menu_is_publicly_browseable_with_served_local_images(seeded_db):
    from fastapi.testclient import TestClient

    from app.main import app

    apply_seed(seeded_db, ORIGINAL_SEED)
    apply_seed(seeded_db, EXPANDED_SEED)
    expected_names = {name for items in EXPECTED_MENU.values() for name in items}

    with TestClient(app) as client:
        response = client.get("/menu/products")
        assert response.status_code == 200
        expanded = [row for row in response.json() if row["name"] in expected_names]
        assert len(expanded) == 40
        assert {row["name"] for row in expanded} == expected_names
        for row in expanded:
            assert Decimal(str(row["price"])) == EXPECTED_MENU[row["category_name"]][row["name"]]

        for image_url in {row["image_url"] for row in expanded}:
            response = client.get(image_url)
            assert response.status_code == 200
            expected_type = "image/svg+xml" if image_url.endswith(".svg") else "image/jpeg"
            assert response.headers["content-type"].split(";", 1)[0] == expected_type
            assert response.content == (ROOT / "app" / image_url.lstrip("/")).read_bytes()


def test_expansion_is_idempotent_and_preserves_original_rows(seeded_db):
    apply_seed(seeded_db, ORIGINAL_SEED)
    apply_seed(seeded_db, EXPANDED_SEED)
    products = snapshot(seeded_db, "products")
    categories = snapshot(seeded_db, "categories")

    apply_seed(seeded_db, ORIGINAL_SEED)
    apply_seed(seeded_db, EXPANDED_SEED)
    apply_seed(seeded_db, EXPANDED_SEED)

    assert snapshot(seeded_db, "products") == products
    assert snapshot(seeded_db, "categories") == categories
    assert Counter(row["name"].lower() for row in categories.values()) == {
        "espresso based": 1, "coffee": 1, "beverages": 1, "snacks": 1, "bites": 1,
    }


def test_expansion_preserves_custom_inactive_rows_and_skips_name_or_sku_conflicts(seeded_db):
    apply_seed(seeded_db, ORIGINAL_SEED)
    with seeded_db, seeded_db.cursor() as cur:
        cur.execute(
            """
            UPDATE products SET name = 'americano', price = 29000,
                image_url = '/custom-americano.jpg', is_active = FALSE
            WHERE sku = 'COF-AMERICANO';
            INSERT INTO categories (name, description)
            VALUES ('bEvErAgEs', 'Owner description; preserve this.');
            INSERT INTO products (category_id, sku, name, price, image_url, is_active) VALUES
                (1, 'CUSTOM-KYOTO', 'kyoto cold brew', 41000, '/custom-kyoto.jpg', FALSE),
                (1, 'COF-TOKYO-LATTE', 'Owner Special', 43000, '/custom-special.jpg', FALSE),
                (1, 'CUSTOM-KINAKO-MILK', 'KINAKO MILK', 39000, '/custom-milk.jpg', FALSE);
            """
        )
    before_products = snapshot(seeded_db, "products")
    before_categories = snapshot(seeded_db, "categories")

    apply_seed(seeded_db, EXPANDED_SEED)
    apply_seed(seeded_db, EXPANDED_SEED)
    after_products = snapshot(seeded_db, "products")
    after_categories = snapshot(seeded_db, "categories")
    assert {key: after_products[key] for key in before_products} == before_products
    assert {key: after_categories[key] for key in before_categories} == before_categories
    assert len(after_products) - len(before_products) == 37
    for name in ("kyoto cold brew", "kinako milk", "americano"):
        assert sum(row["name"].lower() == name for row in after_products.values()) == 1
    assert not any(row["name"] == "Tokyo Vanilla Latte" for row in after_products.values())
    beverage_categories = [row for row in after_categories.values() if row["name"].lower() == "beverages"]
    assert len(beverage_categories) == 1
    beverage_id = beverage_categories[0]["id"]
    assert sum(row["category_id"] == beverage_id for row in after_products.values()) == 9


def test_reseed_keeps_edits_to_new_menu_items(seeded_db):
    apply_seed(seeded_db, ORIGINAL_SEED)
    apply_seed(seeded_db, EXPANDED_SEED)
    with seeded_db, seeded_db.cursor() as cur:
        cur.execute(
            """
            UPDATE products SET name = 'Seasonal Owner Coffee', price = 44000,
                image_url = '/owner-seasonal.jpg', is_active = FALSE, category_id = 1
            WHERE sku = 'COF-KYOTO-COLD-BREW';
            UPDATE categories SET description = 'Owner snacks description'
            WHERE name = 'Snacks';
            """
        )
    products = snapshot(seeded_db, "products")
    categories = snapshot(seeded_db, "categories")
    apply_seed(seeded_db, EXPANDED_SEED)
    assert snapshot(seeded_db, "products") == products
    assert snapshot(seeded_db, "categories") == categories


def test_expansion_can_run_without_applying_the_original_seed(seeded_db):
    before = snapshot(seeded_db, "products")
    apply_seed(seeded_db, EXPANDED_SEED)
    after = snapshot(seeded_db, "products")
    assert len(after) - len(before) == 40
    assert {key: after[key] for key in before} == before
    assert not any(row["sku"] == "COF-AMERICANO" for row in after.values())


def test_noncoffee_assets_are_self_contained_accessible_category_illustrations():
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    assert len(set(ILLUSTRATIONS.values())) == 3
    for category, image_url in ILLUSTRATIONS.items():
        asset = ROOT / "app" / image_url.lstrip("/")
        svg = ElementTree.parse(asset).getroot()
        assert svg.tag == "{http://www.w3.org/2000/svg}svg"
        assert svg.attrib["viewBox"] == "0 0 800 640"
        title = svg.find("svg:title", namespace)
        desc = svg.find("svg:desc", namespace)
        assert title is not None and category.lower() in title.text.lower()
        assert desc is not None and "not a product photograph" in desc.text
        assert svg.attrib["aria-labelledby"] == "title desc"
        assert svg.find(".//svg:image", namespace) is None
        assert all(
            not value.startswith(("http://", "https://", "//", "data:"))
            for element in svg.iter() for key, value in element.attrib.items()
            if key.endswith("href")
        )


def test_cli_dry_run_prints_only_003_without_loading_database(monkeypatch, capsys):
    import sys

    from app.seed_menu import main

    monkeypatch.setitem(sys.modules, "app.database", None)
    assert main(["--dry-run"]) == 0
    assert capsys.readouterr().out == EXPANDED_SEED.read_text(encoding="utf-8")


def test_cli_defaults_to_only_003_and_check_is_read_only(monkeypatch, capsys):
    from unittest.mock import MagicMock

    import app.database
    from app.seed_menu import CHECK_SQL, main

    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    connection.exec_driver_sql.return_value.fetchall.return_value = [("SKU", "Menu")]
    monkeypatch.setattr(app.database, "engine", engine)
    assert main([]) == 0
    connection.exec_driver_sql.assert_called_once_with(EXPANDED_SEED.read_text(encoding="utf-8"))
    engine.begin.assert_called_once_with()
    engine.dispose.assert_called_once_with()
    assert "Added 1" in capsys.readouterr().out

    engine.reset_mock()
    connection.exec_driver_sql.return_value.mappings.return_value.all.return_value = [
        {"name": "Coffee", "total": 28, "active": 27, "inactive": 1},
    ]
    assert main(["--check"]) == 0
    assert [call.args[0] for call in connection.exec_driver_sql.call_args_list] == [
        "SET TRANSACTION READ ONLY", CHECK_SQL,
    ]
    assert "Coffee: 28 total (27 active, 1 inactive)" in capsys.readouterr().out


def test_cli_rolls_back_failed_seed_without_printing_success(monkeypatch, capsys):
    from unittest.mock import MagicMock

    import pytest
    from sqlalchemy.exc import SQLAlchemyError

    import app.database
    from app.seed_menu import main

    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value.exec_driver_sql.side_effect = SQLAlchemyError("failure")
    monkeypatch.setattr(app.database, "engine", engine)
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 1
    assert engine.begin.return_value.__exit__.call_args.args[0] is SQLAlchemyError
    engine.dispose.assert_called_once_with()
    output = capsys.readouterr()
    assert "Added" not in output.out
    assert "no changes committed" in output.err
