from decimal import Decimal
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_purchase_adjustment_and_waste_mutations(seeded_db, manager_headers, cashier_headers):
    po = client.post(
        "/purchases",
        headers=manager_headers,
        json={
            "supplier_id": 1,
            "notes": "Weekly beans restock",
            "items": [{"raw_material_id": 1, "quantity": "500.00", "unit_price": "220.00"}],
        },
    )
    assert po.status_code == 201
    mat = client.get("/raw-materials/1", headers=cashier_headers).json()
    assert Decimal(mat["current_stock"]) == Decimal("600.00")
    assert Decimal(mat["latest_purchase_price"]) == Decimal("220.00")

    adj = client.post(
        "/inventory/adjustment",
        headers=manager_headers,
        json={"raw_material_id": 1, "actual_stock": "585.00", "notes": "Opname variance"},
    )
    assert adj.status_code == 200
    assert Decimal(adj.json()["quantity"]) == Decimal("15.00")
    assert Decimal(adj.json()["stock_before"]) == Decimal("600.00")
    assert Decimal(adj.json()["stock_after"]) == Decimal("585.00")

    waste = client.post(
        "/inventory/waste",
        headers=cashier_headers,
        json={"raw_material_id": 1, "quantity": "5.00", "notes": "Grinder calibration"},
    )
    assert waste.status_code == 200
    muts = client.get("/inventory/1/mutations", headers=cashier_headers).json()
    assert [m["mutation_type"] for m in muts] == ["waste", "adjustment", "in"]