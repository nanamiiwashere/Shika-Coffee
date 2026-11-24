const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function createPos({ href = 'http://localhost:8000/pos', assign = () => {}, replaceState = () => {} } = {}) {
  const storage = new Map();
  const context = {
    window: { location: { href, assign }, history: { replaceState } }, localStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) },
    setTimeout, clearTimeout, AbortController, URL, URLSearchParams, console,
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/js/app.js'), 'utf8'), context);
  const pos = context.shikaPos();
  pos.token = 'test-session';
  return pos;
}

const latte = { id: 1, category_id: 1, name: 'Latte', sku: 'COF-LAT', price: '5.50', image_url: '/latte.png' };

test('switching authentication modes clears passwords and feedback', () => {
  const pos = createPos();
  pos.loginForm.password = 'private-login';
  pos.registerForm.password = pos.registerForm.confirm_password = 'private-register';
  pos.showPassword = pos.showConfirmPassword = true;
  pos.authError = 'Old error';
  pos.setAuthMode('register');
  assert.equal(pos.authMode, 'register');
  assert.equal(pos.loginForm.password, '');
  assert.equal(pos.registerForm.password, '');
  assert.equal(pos.showPassword, false);
  assert.equal(pos.showConfirmPassword, false);
  assert.equal(pos.authError, '');
});

test('registration rejects mismatched passwords without sending a request', async () => {
  const pos = createPos();
  pos.registerForm.password = 'password123';
  pos.registerForm.confirm_password = 'different123';
  pos.authRequest = async () => assert.fail('Mismatched passwords must not be submitted');
  await pos.register();
  assert.match(pos.authError, /don’t match/);
  assert.equal(pos.loading, false);
});

test('registration sends only public fields and waits for admin activation', async () => {
  const pos = createPos();
  pos.token = '';
  pos.authMode = 'register';
  pos.registerForm = { full_name: '  Hana Shika  ', email: ' hana@example.com ', username: ' hana ', password: 'password123', confirm_password: 'password123', role: 'admin', is_active: true };
  let sent;
  pos.authRequest = async (endpoint, options) => {
    assert.equal(endpoint, '/auth/register');
    sent = JSON.parse(options.body);
    return { status: 'pending', message: 'Account created. Please wait for admin activation before signing in.' };
  };
  await pos.register();
  assert.deepEqual(sent, { full_name: 'Hana Shika', email: 'hana@example.com', username: 'hana', password: 'password123' });
  assert.equal(pos.authMode, 'login');
  assert.equal(pos.loginForm.identifier, 'hana@example.com');
  assert.equal(pos.registerForm.password, '');
  assert.equal(pos.registerForm.confirm_password, '');
  assert.equal(pos.token, '');
  assert.match(pos.authMessage, /admin activation/);
});

test('registration displays duplicate errors and clears sensitive fields', async () => {
  const pos = createPos();
  pos.registerForm = { full_name: 'Hana', email: 'hana@example.com', username: 'hana', password: 'password123', confirm_password: 'password123' };
  pos.authRequest = async () => { throw new Error('Email or username already registered'); };
  await pos.register();
  assert.match(pos.authError, /already registered/);
  assert.equal(pos.registerForm.password, '');
  assert.equal(pos.loading, false);
});

test('login validates the staff session before reporting success', async () => {
  const pos = createPos();
  pos.loginForm = { identifier: ' hana ', password: 'password123' };
  pos.authRequest = async (endpoint, options) => {
    assert.equal(endpoint, '/auth/login');
    assert.deepEqual(JSON.parse(options.body), { identifier: 'hana', password: 'password123' });
    return { access_token: 'new-access-token' };
  };
  pos.bootstrapSession = async () => true;
  pos.notify = message => assert.match(message, /successfully/);
  await pos.login();
  assert.equal(pos.token, 'new-access-token');
  assert.equal(pos.loginForm.password, '');
  assert.equal(pos.loading, false);
});

test('failed session bootstrap returns to login instead of exposing a broken workspace', async () => {
  const pos = createPos();
  pos.authRequest = async () => ({ access_token: 'new-access-token' });
  pos.api = async () => { throw new Error('Account inactive'); };
  pos.notify = () => assert.fail('Failed login must not report success');
  await pos.login();
  assert.equal(pos.token, '');
  assert.equal(pos.user, null);
  assert.match(pos.authError, /inactive/);
});

for (const [provider, origin] of [['google', 'https://accounts.google.com'], ['discord', 'https://discord.com']]) {
  test(provider + ' OAuth uses the cookie-bound browser flow', async () => {
    let destination;
    const pos = createPos({ assign: url => { destination = url; } });
    pos.authRequest = async endpoint => {
      assert.equal(endpoint, '/auth/oauth/' + provider + '?mode=json&flow=browser');
      return { authorize_url: origin + '/authorize?state=signed-state' };
    };
    await pos.startOAuth(provider);
    assert.equal(new URL(destination).origin, origin);
    assert.equal(pos.oauthLoading, provider);
  });
}

test('unconfigured OAuth shows an actionable error and re-enables buttons', async () => {
  const pos = createPos();
  pos.authRequest = async () => { throw new Error('Google OAuth is not configured. Contact the administrator.'); };
  await pos.startOAuth('google');
  assert.match(pos.authError, /not configured/);
  assert.equal(pos.oauthLoading, '');
});

test('OAuth rejects an unexpected external redirect destination', async () => {
  const pos = createPos({ assign: () => assert.fail('Untrusted redirect must not be followed') });
  pos.authRequest = async () => ({ authorize_url: 'https://untrusted.example/authorize' });
  await pos.startOAuth('discord');
  assert.match(pos.authError, /Invalid sign-in destination/);
  assert.equal(pos.oauthLoading, '');
});

test('OAuth success exchanges the cookie and removes feedback from browser history', async () => {
  let cleanedUrl;
  const pos = createPos({ href: 'http://localhost:8000/pos?other=1&oauth=success#top', replaceState: (_, __, url) => { cleanedUrl = url; } });
  pos.authRequest = async (endpoint, options) => {
    assert.equal(endpoint, '/auth/oauth/session');
    assert.equal(options.method, 'POST');
    return { access_token: 'oauth-access-token' };
  };
  pos.bootstrapSession = async () => true;
  pos.notify = () => {};
  await pos.init();
  assert.equal(cleanedUrl, '/pos?other=1#top');
  assert.equal(pos.token, 'oauth-access-token');
  assert.equal(pos.loading, false);
});

test('expired OAuth handoff does not keep an old staff session', async () => {
  const pos = createPos({ href: 'http://localhost:8000/pos?oauth=success' });
  pos.authRequest = async () => { throw new Error('Invalid or expired OAuth session'); };
  await pos.init();
  assert.equal(pos.token, '');
  assert.match(pos.authError, /expired/);
  assert.equal(pos.loading, false);
});

test('pending OAuth registration provides approval guidance without exchanging credentials', async () => {
  const pos = createPos({ href: 'http://localhost:8000/pos?oauth=pending' });
  pos.token = '';
  pos.authRequest = async () => assert.fail('Pending accounts receive no session');
  await pos.init();
  assert.equal(pos.token, '');
  assert.match(pos.authMessage, /admin activation/);
});

test('money uses Indonesian rupiah grouping without changing amounts', () => {
  const pos = createPos();
  const money = value => pos.formatMoney(value).replace(/\s/g, ' ');
  assert.equal(money(25000), 'Rp 25.000');
  assert.equal(money('1250000.50'), 'Rp 1.250.000,5');
  assert.equal(money('4.50'), 'Rp 4,5');
  assert.equal(money(0), 'Rp 0');
  assert.equal(money(null), 'Rp 0');
});

test('catalog filtering is instant, category-aware, and case insensitive', () => {
  const pos = createPos();
  pos.allProducts = [latte, { id: 2, category_id: 2, name: 'Matcha', sku: 'TEA-MAT', price: '4.00' }];
  pos.selectedCategory = 1;
  pos.searchQuery = ' LAT ';
  pos.applyFilters();
  assert.equal(pos.products.length, 1);
  assert.equal(pos.products[0].id, 1);
  pos.selectCategory(2);
  assert.equal(pos.products.length, 0);
  pos.searchQuery = '';
  pos.applyFilters();
  assert.equal(pos.products[0].id, 2);
  assert.equal(pos.countByCategory(1), 1);
});

test('category badges reflect actual product stock flags', () => {
  const pos = createPos();
  pos.allProducts = [latte, { id: 2, category_id: 2, is_low_stock: true }];
  assert.equal(pos.categoryLowStock(1), false);
  assert.equal(pos.categoryLowStock(2), true);
});

test('cart keeps thumbnails and notes, updates quantities and removes zero rows', () => {
  const pos = createPos();
  pos.addToCart(latte);
  pos.addToCart(latte);
  assert.equal(pos.cart.length, 1);
  assert.equal(pos.cartQty(1), 2);
  assert.equal(pos.cart[0].image_url, '/latte.png');
  pos.cart[0].notes = 'Less sugar';
  pos.changeQty(0, -1);
  assert.equal(pos.cart[0].notes, 'Less sugar');
  pos.changeQty(0, -1);
  assert.equal(pos.cart.length, 0);
});

test('subtotal, ten percent tax, and cash change use cent rounding', () => {
  const pos = createPos();
  pos.addToCart({ ...latte, id: 2, price: '4.55' });
  pos.addToCart(latte);
  assert.equal(pos.cartSubtotal(), 10.05);
  assert.equal(pos.cartTax(), 1.01);
  assert.equal(pos.cartTotal(), 11.06);
  pos.paymentMethod = 'cash';
  pos.amountPaid = '20';
  assert.equal(pos.cashChange(), 8.94);
});

test('checkout rejects empty carts and duplicate submissions', async () => {
  const pos = createPos();
  let calls = 0;
  pos.api = async () => { calls++; };
  await pos.checkout();
  assert.equal(calls, 0);
  pos.addToCart(latte);
  pos.loading = true;
  await pos.checkout();
  assert.equal(calls, 0);
});

test('checkout preserves order data and sends only supported sale fields', async () => {
  const pos = createPos();
  let payload;
  pos.customerName = 'Hana';
  pos.tableNumber = 'B2';
  pos.addToCart(latte);
  pos.cart[0].notes = ' Less sugar ';
  pos.api = async (url, options) => {
    if (url === '/sales') {
      payload = JSON.parse(options.body);
      return { id: 10, invoice_number: 'INV-10' };
    }
    if (url === '/sales/10/receipt') return { invoice_number: 'INV-10' };
    return [];
  };
  pos.loadSales = async () => {};
  pos.loadStock = async () => {};
  pos.loadProducts = async () => {};
  pos.notify = () => {};
  await pos.checkout();
  assert.equal(payload.customer_name, 'Hana (Table B2)');
  assert.equal(payload.tax, '0.55');
  assert.equal(payload.amount_paid, '6.05');
  assert.equal(payload.items[0].notes, 'Less sugar');
  assert.deepEqual(Object.keys(payload.items[0]).sort(), ['notes', 'product_id', 'quantity']);
  assert.equal(pos.cart.length, 0);
  assert.equal(pos.receiptModal.invoice_number, 'INV-10');
});

test('failed checkout keeps the cart for retry', async () => {
  const pos = createPos();
  pos.addToCart(latte);
  pos.api = async () => { throw new Error('Insufficient raw material stock'); };
  let message;
  pos.notify = text => { message = text; };
  await pos.checkout();
  assert.equal(pos.cartQty(1), 1);
  assert.match(message, /stock/);
  assert.equal(pos.loading, false);
});

test('images have a local fallback and reject unsafe URL protocols', () => {
  const pos = createPos();
  assert.equal(pos.productImage({}), '/static/images/product-placeholder.svg');
  assert.equal(pos.productImage({ image_url: 'javascript:alert(1)' }), '/static/images/product-placeholder.svg');
  assert.equal(pos.productImage(latte), '/latte.png');
});

test('daily count uses the uncapped summary endpoint', async () => {
  const pos = createPos();
  let endpoint;
  pos.api = async url => { endpoint = url; return { order_count: 215 }; };
  await pos.loadSales();
  assert.equal(endpoint, '/sales/summary/today');
  assert.equal(pos.orderCount, 215);
  assert.equal(pos.draftOrderNumber, '#00216');
});

test('cart cannot change while payment is processing', () => {
  const pos = createPos();
  pos.addToCart(latte);
  pos.loading = true;
  pos.addToCart(latte);
  assert.equal(pos.cartQty(1), 1);
  pos.changeQty(0, -1);
  assert.equal(pos.cartQty(1), 1);
});

test('a completed sale is not retried when receipt retrieval fails', async () => {
  const pos = createPos();
  pos.addToCart(latte);
  let submissions = 0;
  let message;
  pos.api = async (url, options) => {
    if (options?.method === 'POST') { submissions++; return { id: 10, invoice_number: 'INV-10' }; }
    throw new Error('Connection lost');
  };
  pos.notify = text => { message = text; };
  pos.loadSales = async () => {};
  pos.loadStock = async () => {};
  pos.loadProducts = async () => {};
  await pos.checkout();
  assert.equal(pos.cart.length, 0);
  assert.equal(pos.loading, false);
  assert.match(message, /INV-10.*completed/);
  await pos.checkout();
  assert.equal(submissions, 1);
});

test('signing out clears private UI state', () => {
  const pos = createPos();
  pos.token = 'private-token';
  pos.orderCount = 10;
  pos.lowStockItems = [{ name: 'Beans' }];
  pos.notificationsOpen = true;
  pos.toast = { show: true, message: 'Private order', type: 'success' };
  pos.addToCart(latte);
  pos.logout();
  assert.equal(pos.cart.length, 0);
  assert.equal(pos.lowStockItems.length, 0);
  assert.equal(pos.orderCount, 0);
  assert.equal(pos.notificationsOpen, false);
  assert.equal(pos.toast.show, false);
});
