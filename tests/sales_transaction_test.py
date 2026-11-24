# tests/test_sales_transactions.py
from decimal import Decimal
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app


@pytest.mark.anyio
async def test_sale_deducts_recipe_stock_and_cancels_cleanly(seeded_db, cashier_headers, manager_headers):
    """
    SEEDED_DB fixture provides:
      - raw_material id=1 (Espresso Beans): current_stock=100.00
      - raw_material id=2 (Fresh Milk): current_stock=500.00
      - product id=1 (Latte, price=25000.00): 18.00g Beans + 150.00ml Milk
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Sell 2 Lattes -> requires 36g Beans, 300ml Milk
        res = await client.post(
            "/sales",
            headers=cashier_headers,
            json={
                "customer_name": "Budi",
                "order_type": "dine_in",
                "discount": "0.00",
                "tax": "5000.00",
                "payment_method": "qris",
                "amount_paid": "55000.00",
                "items": [{"product_id": 1, "quantity": 2, "notes": "Less ice"}],
            },
        )
        assert res.status_code == 201
        sale = res.json()
        assert Decimal(sale["total_amount"]) == Decimal("55000.00")
        assert Decimal(sale["change_amount"]) == Decimal("0.00")

        # 2. Verify stock dropped to 64g Beans and 200ml Milk
        inv = (await client.get("/inventory", headers=cashier_headers)).json()
        by_id = {row["id"]: Decimal(row["current_stock"]) for row in inv}
        assert by_id[1] == Decimal("64.00")
        assert by_id[2] == Decimal("200.00")

        # 3. Attempt to sell 4 more Lattes (needs 72g Beans > 64g) -> must fail 409 and rollback
        fail_res = await client.post(
            "/sales",
            headers=cashier_headers,
            json={
                "payment_method": "cash",
                "amount_paid": "100000.00",
                "items": [{"product_id": 1, "quantity": 4}],
            },
        )
        assert fail_res.status_code == 409

        # Stock must remain untouched at 64g / 200ml
        inv_after_fail = (await client.get("/inventory", headers=cashier_headers)).json()
        by_id_after = {row["id"]: Decimal(row["current_stock"]) for row in inv_after_fail}
        assert by_id_after[1] == Decimal("64.00")
        assert by_id_after[2] == Decimal("200.00")

        # 4. Manager cancels sale -> restores 36g Beans and 300ml Milk
        cancel_res = await client.post(f"/sales/{sale['id']}/cancel", headers=manager_headers)
        assert cancel_res.status_code == 200

        inv_restored = (await client.get("/inventory", headers=cashier_headers)).json()
        by_id_restored = {row["id"]: Decimal(row["current_stock"]) for row in inv_restored}
        assert by_id_restored[1] == Decimal("100.00")
        assert by_id_restored[2] == Decimal("500.00")