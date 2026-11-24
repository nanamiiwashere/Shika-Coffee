from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.security import OAUTH_CONFIG

REPO_ROOT = Path(__file__).resolve().parent.parent
client = TestClient(app)


def _get_valid_oauth_state(tc: TestClient, provider: str = "google") -> str:
    res = tc.get(f"/auth/oauth/{provider}?mode=json")
    assert res.status_code == 200
    query = parse_qs(urlparse(res.json()["authorize_url"]).query)
    return query["state"][0]


def test_html_pages_render_ok():
    for path in ("/", "/login", "/signup", "/pos", "/pos/orders", "/orders", "/dashboard", "/reports-page"):
        res = client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]

    assert client.get("/inventory-page").status_code == 404

    login_html = client.get("/login").text
    assert 'id="login-form"' in login_html
    assert 'id="register-form"' not in login_html
    assert "shika-logo.png" not in login_html
    assert 'class="pos-workspace' not in login_html

    signup_html = client.get("/signup").text
    assert 'id="register-form"' in signup_html
    assert 'id="login-form"' not in signup_html
    assert "shika-logo.png" not in signup_html
    assert 'class="pos-workspace' not in signup_html

    pos_html = client.get("/pos").text
    assert 'class="pos-login' not in pos_html
    assert 'id="login-form"' not in pos_html
    assert 'id="register-form"' not in pos_html

    orders_html = client.get("/pos/orders").text
    assert 'x-data="shikaOrders()"' in orders_html
    assert "pos-kds-board" in orders_html
    assert "Bar Queue" in orders_html
    assert "Served History" in orders_html
    assert "pos-stage-cards" not in orders_html
    assert "Payment Details" not in orders_html
    board_start = orders_html.index('class="pos-kds-board"')
    board_end = orders_html.index("</section>", board_start)
    assert "formatMoney(" not in orders_html[board_start:board_end]
    assert "Item Breakdown" in orders_html
    assert "Order Total" in orders_html
    assert "Print Receipt" in orders_html
    assert "pos-kds-history-table" in orders_html
    assert "prevStageOf" not in orders_html
    assert "Back to " not in orders_html
    app_js = (REPO_ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "shika_bar_stages" in app_js
    for stage_label in ("Queued", "Brewing", "Ready", "Start Brew", "Mark Ready", "Complete"):
        assert stage_label in app_js

    dashboard_html = client.get("/dashboard").text
    assert 'x-data="shikaReports()"' in dashboard_html
    assert "admin-theme.css" in dashboard_html
    assert "adm-sidebar" in dashboard_html
    assert "Dark Mode" not in dashboard_html
    assert "Accent Theme" not in dashboard_html
    assert "COGS &amp; Gross Margin Ledger" not in dashboard_html
    assert "COGS & Gross Margin Ledger" not in dashboard_html
    assert "Full Warehouse" not in dashboard_html
    for section_label in (
        "Overview",
        "POS System",
        "Orders",
        "Sales &amp; Voids",
        "Menu &amp; Recipes",
        "Roastery &amp; Beans",
        "Purchasing &amp; Suppliers",
        "Reports &amp; Analytics",
        "Staff Users",
    ):
        assert section_label in dashboard_html or section_label.replace("&amp;", "&") in dashboard_html
    for marker in (
        "Sales Revenue",
        "Live Bar Queue",
        "Top Drinks &amp; Snacks Today",
        "Roastery Stock Watchlist",
        "Shift Notes",
        "Log Note",
        "Profile &amp; Account Settings",
        "Tender Breakdown",
        "Quick Reason Presets",
        "Available on POS",
        "Bean Stock Distribution",
        "Stock Opname",
        "Record Waste",
        "New Purchase Order",
        "Suppliers Directory",
        "Revenue Breakdown by Payment",
        "Product Margin &amp; Costing Analysis",
        "Export CSV",
        "+ Add Staff",
    ):
        assert marker in dashboard_html or marker.replace("&amp;", "&") in dashboard_html
    assert "pos-header-quicklinks" not in dashboard_html

    for unified_html in (pos_html, orders_html, dashboard_html):
        assert "admin-theme.css" in unified_html
        assert "adm-sidebar" in unified_html
        assert "shika-logo.png" in unified_html
        assert "Profile &amp; Account Settings" in unified_html
        assert "adm-print-popup" in unified_html
        assert "Receipt printed" in unified_html
        assert "adm-receipt-card print-receipt-card" in unified_html
        assert "A little happiness, on its way" in unified_html
        assert "Thank you for making a little time for Shika." in unified_html
        assert "pos-kds-modal print-receipt-card" not in unified_html
        assert "Dark Mode" not in unified_html
        assert "Accent Theme" not in unified_html
        assert "/inventory-page" not in unified_html
        assert 'id="prof-avatar"' not in unified_html
        assert "Profile Photo URL" not in unified_html
        assert 'id="pf-img"' not in unified_html
        assert "Image URL" not in unified_html
        assert 'href="/pos"' in unified_html
        assert 'href="/pos/orders"' in unified_html
        topbar_start = unified_html.index('class="adm-topbar"')
        topbar_block = unified_html[topbar_start : unified_html.index("</header>", topbar_start)]
        assert 'href="/pos"' not in topbar_block
        assert 'href="/pos/orders"' not in topbar_block

    landing_html = client.get("/").text
    assert "data-landing-staff-link" not in landing_html
    assert "data-landing-video-open" in landing_html
    assert "https://www.youtube-nocookie.com/embed/xnU24EjThyM?autoplay=1&amp;controls=0&amp;rel=0&amp;iv_load_policy=3&amp;playsinline=1&amp;modestbranding=1" in landing_html or "https://www.youtube-nocookie.com/embed/xnU24EjThyM?autoplay=1&controls=0&rel=0&iv_load_policy=3&playsinline=1&modestbranding=1" in landing_html


def test_unique_and_fk_constraints_return_409(seeded_db, admin_headers):
    dup_cat = client.post("/categories", headers=admin_headers, json={"name": "Espresso Based"})
    assert dup_cat.status_code == 409
    assert "detail" in dup_cat.json()

    dup_sku = client.post(
        "/products",
        headers=admin_headers,
        json={"category_id": 1, "sku": "MNU-LATTE", "name": "Latte Copy", "price": "25000.00"},
    )
    assert dup_sku.status_code == 409
    assert "detail" in dup_sku.json()

    del_cat = client.delete("/categories/1", headers=admin_headers)
    assert del_cat.status_code == 409
    assert "detail" in del_cat.json()

    del_unit = client.delete("/units/1", headers=admin_headers)
    assert del_unit.status_code == 409
    assert "detail" in del_unit.json()


def test_query_param_validation_422(seeded_db, cashier_headers, manager_headers):
    bad_status = client.get("/sales?status=invalid", headers=cashier_headers)
    assert bad_status.status_code == 422

    bad_days = client.get("/reports/top-products?days=0", headers=manager_headers)
    assert bad_days.status_code == 422


def test_sale_notes_and_deterministic_item_order(seeded_db, manager_headers, cashier_headers):
    prod2 = client.post(
        "/products",
        headers=manager_headers,
        json={"category_id": 1, "sku": "MNU-AMER", "name": "Americano", "price": "20000.00"},
    )
    assert prod2.status_code == 201
    prod2_id = prod2.json()["id"]

    sale_res = client.post(
        "/sales",
        headers=cashier_headers,
        json={
            "customer_name": "Sari",
            "order_type": "dine_in",
            "payment_method": "qris",
            "amount_paid": "45000.00",
            "items": [
                {"product_id": 1, "quantity": 1, "notes": "Less ice"},
                {"product_id": prod2_id, "quantity": 1, "notes": "Extra hot"},
            ],
        },
    )
    assert sale_res.status_code == 201
    sale_id = sale_res.json()["id"]

    detail = client.get(f"/sales/{sale_id}", headers=cashier_headers)
    assert detail.status_code == 200
    detail_items = detail.json()["items"]
    assert [it["id"] for it in detail_items] == sorted(it["id"] for it in detail_items)
    assert [it["notes"] for it in detail_items] == ["Less ice", "Extra hot"]

    receipt = client.get(f"/sales/{sale_id}/receipt", headers=cashier_headers)
    assert receipt.status_code == 200
    assert [it["notes"] for it in receipt.json()["items"]] == ["Less ice", "Extra hot"]


def test_purchase_total_cost_matches_rounded_subtotals(seeded_db, manager_headers):
    po_res = client.post(
        "/purchases",
        headers=manager_headers,
        json={
            "supplier_id": 1,
            "items": [
                {"raw_material_id": 1, "quantity": "1.11", "unit_price": "10.04"},
                {"raw_material_id": 2, "quantity": "1.11", "unit_price": "10.04"},
            ],
        },
    )
    assert po_res.status_code == 201
    po = client.get(f"/purchases/{po_res.json()['id']}", headers=manager_headers).json()
    item_sum = sum((Decimal(str(it["subtotal"])) for it in po["items"]), Decimal("0.00"))
    assert item_sum == Decimal("22.28")
    assert Decimal(str(po["total_cost"])) == item_sum


def test_create_raw_material_includes_unit_symbol(seeded_db, manager_headers):
    res = client.post(
        "/raw-materials",
        headers=manager_headers,
        json={"unit_id": 1, "sku": "RAW-SUGAR", "name": "Brown Sugar", "minimum_stock": "20.00"},
    )
    assert res.status_code == 201
    assert res.json()["unit_symbol"] == "gr"


def test_oauth_callback_unconfigured_provider_501(monkeypatch):
    monkeypatch.setitem(OAUTH_CONFIG["google"], "client_id", "")
    res = client.get("/auth/oauth/google/callback?code=dummy&state=dummy")
    assert res.status_code == 501


def test_oauth_callback_invalid_state_400(seeded_db, monkeypatch):
    monkeypatch.setitem(OAUTH_CONFIG["google"], "client_id", "cid")
    monkeypatch.setitem(OAUTH_CONFIG["google"], "client_secret", "csec")
    monkeypatch.setattr(
        "app.routers.auth.fetch_oauth_profile",
        lambda provider, code: {
            "provider_user_id": "g-1",
            "email": "cashier@shika.test",
            "email_verified": True,
            "full_name": "Cashier Test",
            "avatar_url": None,
        },
    )
    res = client.get("/auth/oauth/google/callback?code=dummy&state=tampered-state")
    assert res.status_code == 400


def test_oauth_callback_unverified_email_400(seeded_db, monkeypatch):
    monkeypatch.setitem(OAUTH_CONFIG["google"], "client_id", "cid")
    monkeypatch.setitem(OAUTH_CONFIG["google"], "client_secret", "csec")

    class FakeHttpClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            return httpx.Response(200, json={"access_token": "tok"}, request=httpx.Request("POST", url))

        def get(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "sub": "g-unverified",
                    "email": "cashier@shika.test",
                    "email_verified": False,
                    "name": "Bad Actor",
                },
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr("app.security.httpx.Client", FakeHttpClient)
    with TestClient(app) as tc:
        state = _get_valid_oauth_state(tc, "google")
        res = tc.get(f"/auth/oauth/google/callback?code=abc&state={state}")
    assert res.status_code == 400


def test_oauth_callback_upstream_http_error(seeded_db, monkeypatch):
    monkeypatch.setitem(OAUTH_CONFIG["google"], "client_id", "cid")
    monkeypatch.setitem(OAUTH_CONFIG["google"], "client_secret", "csec")

    class FailingHttpClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            return httpx.Response(400, json={"error": "invalid_grant"}, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.security.httpx.Client", FailingHttpClient)
    with TestClient(app) as tc:
        state = _get_valid_oauth_state(tc, "google")
        res = tc.get(f"/auth/oauth/google/callback?code=bad&state={state}")
    assert res.status_code in (400, 502)


def test_frontend_static_and_template_hygiene():
    css = (REPO_ROOT / "app" / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert "[x-cloak]" in css

    for tpl, root_expr in (
        ("login.html", 'x-data="shikaAuth(\'login\')"'),
        ("signup.html", 'x-data="shikaAuth(\'register\')"'),
        ("pos.html", 'x-data="shikaPos()"'),
        ("orders.html", 'x-data="shikaOrders()"'),
        ("reports.html", 'x-data="shikaReports()"'),
    ):
        html = (REPO_ROOT / "app" / "templates" / tpl).read_text(encoding="utf-8")
        assert 'x-init="init()"' not in html
        assert html.count(root_expr) == 1

    auth_partial = (REPO_ROOT / "app" / "templates" / "_auth_panel.html").read_text(encoding="utf-8")
    assert "shika-logo.png" not in auth_partial
    assert "pos-login-brand" not in auth_partial

    app_js = (REPO_ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "window.shikaFetch" in app_js
    assert "function shikaInventory()" not in app_js
    assert "function shikaReports()" in app_js
    assert "function shikaHomeForRole(" in app_js
    assert not (REPO_ROOT / "app" / "templates" / "inventory.html").exists()

    reports_html = (REPO_ROOT / "app" / "templates" / "reports.html").read_text(encoding="utf-8")
    assert 'admin-theme.css' in reports_html
    assert '_adm_sidebar.html' in reports_html
    assert 'id="shift-notes"' in reports_html
    assert 'id="cogs-ledger"' not in reports_html
    assert 'addShiftNote()' in reports_html
    assert "/reports/shift-notes" in app_js
    assert "shika_shift_notes" not in app_js
    assert "triggerReceiptPrint(" in app_js
    assert "saveProfileSettings(" in app_js
    assert "uploadProductImage(" in app_js
    assert "uploadMaterialImage(" in app_js
    assert "_niceChartMax(" in app_js
    assert "+ New Lot" in reports_html
    assert "materialPhotoInput" in reports_html
    assert "productPhotoInput" in reports_html
    assert "adm-tab-enter" in reports_html
    assert "adm-overlay-enter" in reports_html
    assert "adm-panel-enter" in reports_html
    admin_css = (REPO_ROOT / "app" / "static" / "css" / "admin-theme.css").read_text(encoding="utf-8")
    assert "@keyframes admCardRise" in admin_css
    assert "@keyframes admModalIn" in admin_css
    assert "prefers-reduced-motion: reduce" in admin_css

    orders_tpl = (REPO_ROOT / "app" / "templates" / "orders.html").read_text(encoding="utf-8")
    assert "is-leaving" in orders_tpl
    assert "is-entering" in orders_tpl

    admin_css_path = REPO_ROOT / "app" / "static" / "css" / "admin-theme.css"
    assert admin_css_path.exists()
    admin_css = admin_css_path.read_text(encoding="utf-8")
    for token in ("--bg: #f5f3eb;", "--surface: #faf9f5;", "--accent: #14532d;", "--border:", "--text:", "--muted-text:", "--success:", "--warning:", "--danger:", "--font-mono:"):
        assert token in admin_css
    assert '[data-theme="dark"]' not in admin_css
    assert '[data-accent="alt"]' not in admin_css

    pos_css = (REPO_ROOT / "app" / "static" / "css" / "pos.css").read_text(encoding="utf-8")
    assert ".pos-ops-stack" in pos_css
    assert ".pos-ops-pagination" in pos_css
    assert "max-width: 1560px" not in pos_css
    assert client.get("/dashboard?page=2").status_code == 200

    assert not (REPO_ROOT / "app" / "api.js").exists()


def test_user_crud_and_session_pool_reuse(seeded_db, admin_headers):
    created = client.post(
        "/users",
        headers=admin_headers,
        json={
            "email": "barista@shika.com",
            "username": "barista1",
            "password": "password123",
            "full_name": "Barista One",
            "role": "cashier",
        },
    )
    assert created.status_code == 201
    uid = created.json()["id"]

    login_res = client.post("/auth/login", json={"identifier": "barista1", "password": "password123"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    me_ok = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_ok.status_code == 200
    assert me_ok.json()["username"] == "barista1"

    deact = client.delete(f"/users/{uid}", headers=admin_headers)
    assert deact.status_code == 200
    assert deact.json()["is_active"] is False

    me_inactive = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_inactive.status_code == 403

    re_login = client.post("/auth/login", json={"identifier": "barista1", "password": "password123"})
    assert re_login.status_code == 403


def test_profile_account_settings_me_endpoint(seeded_db, cashier_headers):
    import base64

    # GET /auth/me exposes auth methods and password status
    me_init = client.get("/auth/me", headers=cashier_headers)
    assert me_init.status_code == 200
    assert me_init.json()["has_password"] is True
    assert me_init.json()["auth_methods"] == ["password"]

    # Update display name, email, username, and avatar URL as own user
    res = client.patch(
        "/auth/me",
        headers=cashier_headers,
        json={
            "full_name": "Kenji Takahashi",
            "email": "kenji.new@shika.coffee",
            "username": "kenji_bar",
            "avatar_url": "/static/images/shika-logo.png",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["full_name"] == "Kenji Takahashi"
    assert body["email"] == "kenji.new@shika.coffee"
    assert body["username"] == "kenji_bar"
    assert body["avatar_url"] == "/static/images/shika-logo.png"
    assert body["role"] == "cashier"

    # Role escalation must be rejected (extra="forbid")
    esc = client.patch("/auth/me", headers=cashier_headers, json={"role": "admin"})
    assert esc.status_code == 422

    # Unsafe avatar URL must be rejected
    bad_url = client.patch("/auth/me", headers=cashier_headers, json={"avatar_url": "javascript:alert(1)"})
    assert bad_url.status_code == 422

    # Duplicate email and username collisions return 409
    with seeded_db, seeded_db.cursor() as cur:
        cur.execute("UPDATE users SET email = 'admin@shika.coffee' WHERE id = 3")
    assert client.patch("/auth/me", headers=cashier_headers, json={"email": "admin@shika.coffee"}).status_code == 409
    assert client.patch("/auth/me", headers=cashier_headers, json={"username": "admin1"}).status_code == 409

    # Upload profile photo (valid PNG magic bytes) + reject non-image payload
    bad_upload = client.post(
        "/auth/me/avatar",
        headers=cashier_headers,
        json={"image_data": "data:image/png;base64," + base64.b64encode(b"not-a-real-png").decode()},
    )
    assert bad_upload.status_code == 422

    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    up = client.post(
        "/auth/me/avatar",
        headers=cashier_headers,
        json={"image_data": "data:image/png;base64," + base64.b64encode(tiny_png).decode()},
    )
    assert up.status_code == 200
    uploaded_url = up.json()["avatar_url"]
    assert uploaded_url.startswith("/static/uploads/avatars/user_1_")
    uploaded_file = REPO_ROOT / "app" / uploaded_url.lstrip("/")
    assert uploaded_file.is_file()

    # Clearing avatar_url resets it to null and cleans up the local uploaded file
    cleared = client.patch("/auth/me", headers=cashier_headers, json={"avatar_url": ""})
    assert cleared.status_code == 200
    assert cleared.json()["avatar_url"] is None
    assert not uploaded_file.exists()

    # Cannot remove password when it is the only sign-in method
    assert client.delete("/auth/me/password", headers=cashier_headers).status_code == 400

    # Link an OAuth account directly in DB, verify auth_methods lists both, then unlink Google cleanly
    with seeded_db, seeded_db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_oauth_accounts (user_id, provider, provider_user_id, provider_email)
            VALUES (1, 'google', 'g-sub-123', 'kenji.new@shika.test')
            """
        )
    me_both = client.get("/auth/me", headers=cashier_headers).json()
    assert set(me_both["auth_methods"]) == {"password", "google"}
    unlinked = client.delete("/auth/me/oauth/google", headers=cashier_headers)
    assert unlinked.status_code == 200
    assert unlinked.json()["auth_methods"] == ["password"]

    # Password change requires valid current_password
    bad_pw = client.patch(
        "/auth/me",
        headers=cashier_headers,
        json={"current_password": "wrongpassword", "new_password": "newpassword123"},
    )
    assert bad_pw.status_code == 400

    ok_pw = client.patch(
        "/auth/me",
        headers=cashier_headers,
        json={"current_password": "password123", "new_password": "newpassword123"},
    )
    assert ok_pw.status_code == 200

    # New password + updated email work for login and old password fails
    assert client.post("/auth/login", json={"identifier": "kenji_bar", "password": "password123"}).status_code == 401
    assert client.post("/auth/login", json={"identifier": "kenji.new@shika.coffee", "password": "newpassword123"}).status_code == 200


def test_qris_simulation_pay_and_timeout(seeded_db, cashier_headers, monkeypatch):
    from app import qris

    # 1. Verify QR format strings match ISO-18004 ECC-L constants
    expected_fmt = [0x77C4, 0x72F3, 0x7DAA, 0x789D, 0x662F, 0x6318, 0x6C41, 0x6976]
    assert [qris._format_bits_ecc_l(m) for m in range(8)] == expected_fmt

    # 2. Create 5-minute (300s) QRIS session from POS
    created = client.post(
        "/sales/qris/sessions",
        headers=cashier_headers,
        json={"amount": "55000.00", "customer_name": "Haruto (Table A2)"},
    )
    assert created.status_code == 201
    sess = created.json()
    assert sess["status"] == "pending"
    assert sess["timeout_seconds"] == 300
    assert sess["pay_path"] == f"/pos/qris-pay/{sess['session_id']}"
    assert "<svg " in sess["qr_svg"] and "</svg>" in sess["qr_svg"]
    pos_page_text = client.get("/pos").text
    assert "Open Payment Page" not in pos_page_text
    assert "pos-qris-url-link" not in pos_page_text
    assert "Click QR code" not in pos_page_text
    assert "Scan QR code to pay" in pos_page_text

    # 3. Payment link HTML page renders cleanly
    pay_page = client.get(sess["pay_path"])
    assert pay_page.status_code == 200
    assert sess["session_id"] in pay_page.text
    assert "qris-pay-btn" in pay_page.text

    # 4. Paying within 5m succeeds and POS poll immediately observes 'paid' (persisted in Postgres, no-store)
    paid = client.post(f"/sales/qris/sessions/{sess['session_id']}/pay")
    assert paid.status_code == 200
    assert paid.json()["status"] == "paid"
    polled = client.get(f"/sales/qris/sessions/{sess['session_id']}")
    assert polled.status_code == 200
    assert polled.headers.get("cache-control") == "no-store"
    assert polled.json()["status"] == "paid"
    with seeded_db.cursor() as cur:
        cur.execute("SELECT status FROM qris_sessions WHERE session_id = %s", (sess["session_id"],))
        assert cur.fetchone()[0] == "paid"

    # 5. Timeout after 5 minutes (300s) marks session expired and blocks payment with 410 Gone
    from datetime import datetime, timedelta, timezone

    clock = [datetime(2026, 11, 24, 10, 0, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(qris, "_utcnow", lambda: clock[0])
    s2 = client.post(
        "/sales/qris/sessions",
        headers=cashier_headers,
        json={"amount": "32000.00", "customer_name": "Walk-in"},
    ).json()
    assert s2["status"] == "pending"
    clock[0] = clock[0] + timedelta(seconds=301)
    expired_poll = client.get(f"/sales/qris/sessions/{s2['session_id']}")
    assert expired_poll.status_code == 200
    assert expired_poll.json()["status"] == "expired"
    expired_pay = client.post(f"/sales/qris/sessions/{s2['session_id']}/pay")
    assert expired_pay.status_code == 410


def test_shift_notes_database_crud(seeded_db, cashier_headers, manager_headers):
    # Cashiers cannot access backoffice shift notes
    assert client.get("/reports/shift-notes", headers=cashier_headers).status_code == 403

    # Initially empty
    assert client.get("/reports/shift-notes", headers=manager_headers).json() == []

    # Invalid category rejected
    assert client.post(
        "/reports/shift-notes",
        headers=manager_headers,
        json={"category": "invalid", "content": "Bad category"},
    ).status_code == 422

    # Create shift note in DB
    created = client.post(
        "/reports/shift-notes",
        headers=manager_headers,
        json={"category": "flavor", "content": "Ethiopia Guji pulling peach at 93C, 1:16."},
    )
    assert created.status_code == 201
    note = created.json()
    assert note["category"] == "flavor"
    assert note["content"] == "Ethiopia Guji pulling peach at 93C, 1:16."
    assert note["is_done"] is False
    assert note["author_name"] == "Manager Test"
    note_id = note["id"]

    # Listed from DB
    listed = client.get("/reports/shift-notes", headers=manager_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == note_id

    # Toggle done in DB
    patched = client.patch(
        f"/reports/shift-notes/{note_id}",
        headers=manager_headers,
        json={"is_done": True},
    )
    assert patched.status_code == 200
    assert patched.json()["is_done"] is True
    assert patched.json()["author_name"] == "Manager Test"

    # Delete from DB
    deleted = client.delete(f"/reports/shift-notes/{note_id}", headers=manager_headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted_id"] == note_id
    assert client.get("/reports/shift-notes", headers=manager_headers).json() == []
    assert client.delete(f"/reports/shift-notes/{note_id}", headers=manager_headers).status_code == 404


def test_order_management_workflow(seeded_db, cashier_headers, manager_headers):
    sale_res = client.post(
        "/sales",
        headers=cashier_headers,
        json={
            "customer_name": "Luna (Table A2)",
            "order_type": "dine_in",
            "payment_method": "qris",
            "amount_paid": "25000.00",
            "items": [{"product_id": 1, "quantity": 1, "notes": "Less ice"}],
        },
    )
    assert sale_res.status_code == 201
    sale = sale_res.json()
    assert sale["order_status"] == "received"
    sale_id = sale["id"]

    listed = client.get("/sales?include_items=true&order_status=received", headers=cashier_headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["id"] == sale_id
    assert rows[0]["customer_name"] == "Luna (Table A2)"
    assert rows[0]["items"][0]["product_name"] == "Latte"
    assert rows[0]["items"][0]["notes"] == "Less ice"

    assert client.get("/sales?order_status=processing", headers=cashier_headers).json() == []

    for next_stage in ("processing", "ready", "finished"):
        patched = client.patch(
            f"/sales/{sale_id}/order-status",
            headers=cashier_headers,
            json={"order_status": next_stage},
        )
        assert patched.status_code == 200
        assert patched.json()["order_status"] == next_stage

    receipt = client.get(f"/sales/{sale_id}/receipt", headers=cashier_headers)
    assert receipt.status_code == 200
    assert receipt.json()["order_status"] == "finished"

    assert client.patch(
        f"/sales/{sale_id}/order-status",
        headers=cashier_headers,
        json={"order_status": "unknown"},
    ).status_code == 422
    assert client.patch(
        f"/sales/{sale_id}/order-status",
        headers=cashier_headers,
        json={"order_status": "ready", "extra": True},
    ).status_code == 422
    assert client.patch(
        "/sales/999999/order-status",
        headers=cashier_headers,
        json={"order_status": "ready"},
    ).status_code == 404

    assert client.post(f"/sales/{sale_id}/cancel", headers=manager_headers).status_code == 200
    assert client.patch(
        f"/sales/{sale_id}/order-status",
        headers=cashier_headers,
        json={"order_status": "ready"},
    ).status_code == 409


def test_local_uploads_for_products_and_roastery_and_tz_sales_stats(seeded_db, manager_headers, cashier_headers):
    import base64

    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    png_uri = "data:image/png;base64," + base64.b64encode(tiny_png).decode()
    bad_uri = "data:image/png;base64," + base64.b64encode(b"not-a-png").decode()

    # Cashiers cannot upload product or roastery images
    assert client.post("/products/upload-image", headers=cashier_headers, json={"image_data": png_uri}).status_code == 403
    assert client.post("/raw-materials/upload-image", headers=cashier_headers, json={"image_data": png_uri}).status_code == 403

    # Corrupt payloads rejected
    assert client.post("/products/upload-image", headers=manager_headers, json={"image_data": bad_uri}).status_code == 422
    assert client.post("/raw-materials/upload-image", headers=manager_headers, json={"image_data": bad_uri}).status_code == 422

    # External URLs rejected on product & raw material mutations
    assert client.patch(
        "/products/1", headers=manager_headers, json={"image_url": "https://example.com/latte.png"}
    ).status_code == 422
    assert client.patch(
        "/raw-materials/1", headers=manager_headers, json={"image_url": "https://example.com/beans.png"}
    ).status_code == 422

    # Product local upload -> save -> clear removes local file & resets DB column to NULL
    p_up = client.post("/products/upload-image", headers=manager_headers, json={"image_data": png_uri})
    assert p_up.status_code == 200
    p_url = p_up.json()["image_url"]
    assert p_url.startswith("/static/uploads/products/prod_")
    p_file = REPO_ROOT / "app" / p_url.lstrip("/")
    assert p_file.is_file()

    p_patch = client.patch("/products/1", headers=manager_headers, json={"image_url": p_url})
    assert p_patch.status_code == 200
    assert p_patch.json()["image_url"] == p_url

    p_clear = client.patch("/products/1", headers=manager_headers, json={"image_url": None})
    assert p_clear.status_code == 200
    assert p_clear.json()["image_url"] is None
    assert not p_file.exists()

    # Roastery lot local upload -> create -> clear removes local file & resets DB column to NULL
    m_up = client.post("/raw-materials/upload-image", headers=manager_headers, json={"image_data": png_uri})
    assert m_up.status_code == 200
    m_url = m_up.json()["image_url"]
    assert m_url.startswith("/static/uploads/roastery/lot_")
    m_file = REPO_ROOT / "app" / m_url.lstrip("/")
    assert m_file.is_file()

    m_created = client.post(
        "/raw-materials",
        headers=manager_headers,
        json={"unit_id": 1, "sku": "RM-GUJI-LOT", "name": "Ethiopia Guji", "minimum_stock": "200.00", "image_url": m_url},
    )
    assert m_created.status_code == 201
    lot_id = m_created.json()["id"]
    assert m_created.json()["image_url"] == m_url

    m_clear = client.patch(f"/raw-materials/{lot_id}", headers=manager_headers, json={"image_url": None})
    assert m_clear.status_code == 200
    assert m_clear.json()["image_url"] is None
    assert not m_file.exists()

    # Timezone-aware /sales date filtering (WIB UTC+7 => JS getTimezoneOffset() == -420)
    with seeded_db, seeded_db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sales (
                invoice_number, user_id, subtotal, total_amount,
                payment_method, amount_paid, status, transaction_date
            ) VALUES (
                'INV-TZ-WIB-0001', 1, 50000, 50000,
                'cash', 50000, 'completed', '2026-11-22 18:00:00+00'
            )
            """
        )

    # 2026-11-22 18:00 UTC is 2026-11-23 01:00 WIB (+07:00)
    wib_nov23 = client.get(
        "/sales?date_from=2026-11-23&date_to=2026-11-23&tz_offset_minutes=-420",
        headers=manager_headers,
    )
    assert wib_nov23.status_code == 200
    assert [r["invoice_number"] for r in wib_nov23.json()] == ["INV-TZ-WIB-0001"]

    wib_nov22 = client.get(
        "/sales?date_from=2026-11-22&date_to=2026-11-22&tz_offset_minutes=-420",
        headers=manager_headers,
    )
    assert wib_nov22.status_code == 200
    assert wib_nov22.json() == []

    # Dashboard summary accepts tz_offset_minutes cleanly
    dash_tz = client.get("/reports/dashboard?tz_offset_minutes=-420", headers=manager_headers)
    assert dash_tz.status_code == 200
    assert "today_revenue" in dash_tz.json()

    # Revenue and Top Products analytics support tz_offset_minutes + custom date ranges
    rev_nov23 = client.get(
        "/reports/revenue?date_from=2026-11-23&date_to=2026-11-23&tz_offset_minutes=-420",
        headers=manager_headers,
    )
    assert rev_nov23.status_code == 200
    assert len(rev_nov23.json()) == 1
    assert Decimal(str(rev_nov23.json()[0]["net_revenue"])) == Decimal("50000.00")

    rev_nov22 = client.get(
        "/reports/revenue?date_from=2026-11-22&date_to=2026-11-22&tz_offset_minutes=-420",
        headers=manager_headers,
    )
    assert rev_nov22.status_code == 200
    assert rev_nov22.json() == []

    top_range = client.get(
        "/reports/top-products?date_from=2026-11-23&date_to=2026-11-23&tz_offset_minutes=-420",
        headers=manager_headers,
    )
    assert top_range.status_code == 200
    assert isinstance(top_range.json(), list)

    # Python CSV analytics export endpoint + RBAC
    assert client.get(
        "/reports/analytics/export?date_from=2026-11-23&date_to=2026-11-23",
        headers=cashier_headers,
    ).status_code == 403
    csv_res = client.get(
        "/reports/analytics/export?date_from=2026-11-23&date_to=2026-11-23&tz_offset_minutes=-420",
        headers=manager_headers,
    )
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    assert "shika-analytics-2026-11-23-to-2026-11-23.csv" in csv_res.headers["content-disposition"]
    assert "Shika Coffee Analytics Report" in csv_res.text
    assert "Revenue,CASH,cash,1,50000.00" in csv_res.text
    assert "Product Margin,Latte,MNU-LATTE" in csv_res.text

    # Purchasing & Suppliers backend CRUD + multi-item PO + summary endpoint
    assert client.get("/purchases/summary", headers=cashier_headers).status_code == 403
    new_sup = client.post(
        "/suppliers",
        headers=manager_headers,
        json={"name": "Kyoto Matcha Co", "phone": "+628111222333", "email": "orders@kyoto.coffee"},
    )
    assert new_sup.status_code == 201
    sup_id = new_sup.json()["id"]

    po_res = client.post(
        "/purchases",
        headers=manager_headers,
        json={
            "supplier_id": sup_id,
            "notes": "Multi-item delivery",
            "items": [
                {"raw_material_id": 1, "quantity": "200.00", "unit_price": "250.00"},
                {"raw_material_id": 2, "quantity": "1000.00", "unit_price": "20.00"},
            ],
        },
    )
    assert po_res.status_code == 201
    po_id = po_res.json()["id"]
    po_detail = client.get(f"/purchases/{po_id}", headers=manager_headers)
    assert po_detail.status_code == 200
    assert len(po_detail.json()["items"]) == 2

    po_summary = client.get("/purchases/summary", headers=manager_headers)
    assert po_summary.status_code == 200
    assert po_summary.json()["total_orders"] == 1
    assert Decimal(str(po_summary.json()["total_spend"])) == Decimal("70000.00")
    assert po_summary.json()["active_suppliers"] >= 2

    # Units CRUD + Inventory Opname & Waste + Mutation Ledger
    unit_res = client.post("/units", headers=manager_headers, json={"name": "Box", "symbol": "box"})
    assert unit_res.status_code == 201
    unit_id = unit_res.json()["id"]
    assert client.patch(f"/units/{unit_id}", headers=manager_headers, json={"name": "Carton"}).status_code == 200
    assert client.delete(f"/units/{unit_id}", headers=manager_headers).status_code == 204


def test_supabase_and_vercel_configuration(monkeypatch):
    import base64
    import json
    from types import SimpleNamespace
    import httpx
    from app.config import normalize_database_url
    from app.uploads import is_allowed_image_url, remove_local_upload, save_local_image

    vercel_cfg = json.loads((REPO_ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert "rewrites" not in vercel_cfg
    assert vercel_cfg["regions"] == ["sin1"]
    assert vercel_cfg["functions"]["app/main.py"]["includeFiles"] == "app/**"
    assert not (REPO_ROOT / "api").exists()
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"fastapi"' in pyproject and "package = false" in pyproject

    assert normalize_database_url("postgres://u:p@host:6543/postgres") == "postgresql+psycopg2://u:p@host:6543/postgres"
    assert normalize_database_url("postgresql://u:p@host:6543/postgres") == "postgresql+psycopg2://u:p@host:6543/postgres"
    assert normalize_database_url("postgresql+psycopg2://u:p@host:5432/db") == "postgresql+psycopg2://u:p@host:5432/db"
    assert (
        normalize_database_url("postgresql://postgres.ref:p@ss:w#rd@aws-0.pooler.supabase.com:6543/postgres?pgbouncer=true&sslmode=require&connection_limit=1")
        == "postgresql+psycopg2://postgres.ref:p%40ss%3Aw%23rd@aws-0.pooler.supabase.com:6543/postgres?sslmode=require"
    )

    monkeypatch.setenv("SUPABASE_URL", "https://demo-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
    monkeypatch.setenv("SUPABASE_STORAGE_BUCKET", "shika-uploads")

    calls: list[tuple[str, str]] = []

    def fake_post(url, **kwargs):
        calls.append(("POST", url))
        return SimpleNamespace(raise_for_status=lambda: None)

    def fake_delete(url, **kwargs):
        calls.append(("DELETE", url))
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "delete", fake_delete)

    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    uploaded = save_local_image("data:image/png;base64," + base64.b64encode(tiny_png).decode(), "products", "prod")
    assert uploaded.startswith("https://demo-ref.supabase.co/storage/v1/object/public/shika-uploads/products/prod_")
    assert is_allowed_image_url(uploaded) is True
    assert is_allowed_image_url("https://evil.example/a.png") is False
    assert calls[0][0] == "POST"

    remove_local_upload(uploaded, "products")
    assert calls[1][0] == "DELETE"


def test_vercel_cold_start_diagnostics_without_crashing():
    import json
    import os
    import subprocess
    import sys

    # 1. Under VERCEL=1 with missing DATABASE_URL / JWT_SECRET, import succeeds & /health reports 503 misconfigured
    clean_env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "DIRECT_URL", "JWT_SECRET"}}
    clean_env["VERCEL"] = "1"
    clean_env["VERCEL_PROJECT_PRODUCTION_URL"] = "americano.ai.id"
    probe_code = (
        "import json; from fastapi.testclient import TestClient; from app.main import app; "
        "from app.config import CORS_ORIGINS; "
        "c = TestClient(app); h = c.get('/health'); r = c.get('/'); "
        "print(json.dumps({'health_status': h.status_code, 'health': h.json(), 'root_status': r.status_code, 'cors': CORS_ORIGINS}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe_code],
        cwd=str(REPO_ROOT),
        env=clean_env,
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["health_status"] == 503
    assert out["health"]["status"] == "misconfigured"
    assert set(out["health"]["missing_env_vars"]) == {"DATABASE_URL", "JWT_SECRET"}
    assert out["health"]["templates_present"] is True
    assert out["root_status"] == 200
    assert "https://americano.ai.id" in out["cors"]

    # 2. Under VERCEL=1 with malformed DATABASE_URL, import succeeds & /health reports redacted db_error
    bad_env = dict(clean_env)
    bad_env["DATABASE_URL"] = "badscheme://u:topsecret@host/db"
    bad_env["JWT_SECRET"] = "test-secret"
    proc_bad = subprocess.run(
        [sys.executable, "-c", probe_code],
        cwd=str(REPO_ROOT),
        env=bad_env,
        capture_output=True,
        text=True,
        check=True,
    )
    out_bad = json.loads(proc_bad.stdout.strip().splitlines()[-1])
    assert out_bad["health_status"] == 503
    assert out_bad["health"]["missing_env_vars"] == []
    assert out_bad["health"]["db_error"] and "topsecret" not in out_bad["health"]["db_error"]


def test_authenticated_route_uses_single_db_connection(seeded_db, manager_headers, monkeypatch):
    from app import database

    checkouts = 0
    orig_raw_connection = database.engine.raw_connection

    def counting_raw_connection():
        nonlocal checkouts
        checkouts += 1
        return orig_raw_connection()

    monkeypatch.setattr(database.engine, "raw_connection", counting_raw_connection)
    res = client.get("/reports/dashboard", headers=manager_headers)
    assert res.status_code == 200
    assert checkouts == 1


def test_supabase_public_bucket_image_resolution(seeded_db, monkeypatch):
    with seeded_db, seeded_db.cursor() as cur:
        cur.execute("UPDATE products SET image_url = '/static/images/menu/hot-latte.png' WHERE id = 1")

    monkeypatch.setenv("SUPABASE_URL", "https://demo-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_STORAGE_BUCKET", "shika-uploads")
    expected_base = "https://demo-ref.supabase.co/storage/v1/object/public/shika-uploads"

    landing_html = client.get("/").text
    assert f"{expected_base}/shika-logo.png" in landing_html
    assert f"{expected_base}/mascot.png" in landing_html
    assert f'window.SHIKA_IMG_BASE = "{expected_base}"' in landing_html

    menu = client.get("/menu/products").json()
    assert menu[0]["image_url"] == f"{expected_base}/menu/hot-latte.png"

    redir = client.get("/static/images/shika-logo.png", follow_redirects=False)
    assert redir.status_code == 307
    assert redir.headers["location"] == f"{expected_base}/shika-logo.png"


def test_migrate_existing_images_to_supabase_bucket(seeded_db, monkeypatch):
    from types import SimpleNamespace
    import httpx
    import migrate

    with seeded_db, seeded_db.cursor() as cur:
        cur.execute("UPDATE products SET image_url = '/static/images/menu/hot-latte.png' WHERE id = 1")
        cur.execute(
            "INSERT INTO products (category_id, sku, name, price, image_url) VALUES (1, 'MNU-CAP', 'Cappuccino', 28000, '/static/images/menu/hot-latte.png')"
        )
        cur.execute("UPDATE raw_materials SET image_url = '/static/images/shika-logo.png' WHERE id = 1")
        cur.execute("UPDATE users SET avatar_url = '/static/images/missing-file.png' WHERE id = 1")

    posted: list[str] = []

    def fake_post(url, **kwargs):
        posted.append(url)
        if url.endswith("/storage/v1/bucket"):
            return SimpleNamespace(status_code=409, text="already exists", raise_for_status=lambda: None)
        return SimpleNamespace(status_code=200, text="ok", raise_for_status=lambda: None)

    monkeypatch.setattr(httpx, "post", fake_post)

    stats = migrate.migrate_images_to_supabase(
        seeded_db, "https://demo-ref.supabase.co", "service-key", "shika-uploads"
    )
    # 1 bucket check + 2 unique existing files (hot-latte.png shared by 2 products, shika-logo.png on raw_material)
    assert stats == {"files_uploaded": 2, "rows_updated": 3, "skipped": 1}
    assert posted[0] == "https://demo-ref.supabase.co/storage/v1/bucket"
    assert "https://demo-ref.supabase.co/storage/v1/object/shika-uploads/menu/hot-latte.png" in posted
    assert "https://demo-ref.supabase.co/storage/v1/object/shika-uploads/shika-logo.png" in posted

    with seeded_db.cursor() as cur:
        cur.execute("SELECT image_url FROM products WHERE id = 1")
        assert cur.fetchone()[0] == "https://demo-ref.supabase.co/storage/v1/object/public/shika-uploads/menu/hot-latte.png"
        cur.execute("SELECT image_url FROM raw_materials WHERE id = 1")
        assert cur.fetchone()[0] == "https://demo-ref.supabase.co/storage/v1/object/public/shika-uploads/shika-logo.png"
        cur.execute("SELECT avatar_url FROM users WHERE id = 1")
        assert cur.fetchone()[0] == "/static/images/missing-file.png"





