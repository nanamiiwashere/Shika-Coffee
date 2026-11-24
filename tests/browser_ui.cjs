// Optional integration smoke test: run the app, then `node tests/browser_ui.cjs`.
// Uses installed Chrome and Node's built-in DevTools/WebSocket support; no npm packages.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const base = process.env.UI_BASE_URL || 'http://127.0.0.1:8000';
const chromePath = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const root = path.resolve(__dirname, '..');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const categories = [{ id: 1, name: 'Coffee' }, { id: 2, name: 'Tea' }, { id: 3, name: 'Food' }];
const products = ['Americano', 'Cappuccino', 'Espresso', 'Flat White', 'Forest Cold Brew', 'Iced Coffee Milk', 'Mocha', 'Nokotan Latte'].map((name, index) => ({
  id: index + 1, category_id: 1, name, price: (25000 + index * 2500).toFixed(2), sku: 'COF-' + index,
  image_url: '/static/images/coffee-cup.png', category_name: 'Coffee', is_low_stock: false,
}));
products.push({ id: 9, category_id: 2, name: 'Matcha', price: '28000.00', sku: 'TEA-1', category_name: 'Tea', is_low_stock: false });
products.push({ id: 10, category_id: 3, name: 'Toast', price: '15000.00', sku: 'FOOD-1', category_name: 'Food', is_low_stock: true });

async function main() {
  assert.ok(fs.existsSync(chromePath), 'Set CHROME_PATH to an installed Chrome executable');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'shika-ui-check-'));
  const chrome = spawn(chromePath, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], { stdio: 'ignore' });
  let socket;
  let command;
  try {
    const portFile = path.join(profile, 'DevToolsActivePort');
    for (let i = 0; i < 100 && !fs.existsSync(portFile); i++) await pause(100);
    assert.ok(fs.existsSync(portFile), 'Chrome did not start its DevTools endpoint');
    const port = fs.readFileSync(portFile, 'utf8').split('\n')[0].trim();
    const targets = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
    socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }); });
    let id = 0;
    const pending = new Map();
    const exceptions = [];
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
      if (pending.has(message.id)) {
        const { resolve, reject, timer } = pending.get(message.id);
        clearTimeout(timer);
        pending.delete(message.id);
        message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result);
      }
    });
    command = (method, params = {}) => new Promise((resolve, reject) => {
      const key = ++id;
      const timer = setTimeout(() => { pending.delete(key); reject(new Error('DevTools timeout: ' + method)); }, 15000);
      pending.set(key, { resolve, reject, timer });
      socket.send(JSON.stringify({ id: key, method, params }));
    });
    const evaluate = async expression => {
      const result = await command('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    const waitFor = async expression => {
      for (let i = 0; i < 100; i++) { if (await evaluate(expression)) return; await pause(100); }
      throw new Error('Timed out waiting for: ' + expression);
    };
    const assertLogo = async selector => {
      await waitFor(`document.querySelector(${JSON.stringify(selector)})?.complete`);
      assert.equal(await evaluate(`(() => {
        const image = document.querySelector(${JSON.stringify(selector)});
        const rect = image.getBoundingClientRect();
        const container = image.parentElement.getBoundingClientRect();
        return image.naturalWidth === 417 && image.naturalHeight === 565
          && rect.width > 0 && rect.height > 0
          && Math.abs(rect.width / rect.height - image.naturalWidth / image.naturalHeight) < .01
          && rect.left >= container.left - 1 && rect.right <= container.right + 1
          && rect.top >= container.top - 1 && rect.bottom <= container.bottom + 1;
      })()`), true, 'Complete, undistorted Shika logo: ' + selector);
    };
    const assertSectionReveal = async (selector, fromBelow = false) => {
      const deltaY = await evaluate(`(() => {
        const section = document.querySelector(${JSON.stringify(selector)});
        const rect = section.getBoundingClientRect();
        const top = scrollY + rect.top;
        const start = ${fromBelow} ? top + rect.height + 80 : Math.max(0, top - innerHeight - 80);
        window.scrollTo({ top: start, behavior: 'instant' });
        return (${fromBelow} ? -1 : 1) * Math.min(400, innerHeight * .45);
      })()`);
      await waitFor(`!document.querySelector(${JSON.stringify(selector)}).querySelector('[data-landing-reveal]').classList.contains('is-visible')`);
      await pause(1300);
      assert.equal(await evaluate(`getComputedStyle(document.querySelector(${JSON.stringify(selector)}).querySelector('[data-landing-reveal]')).opacity`), '0', 'Off-screen section resets its reveal');
      await command('Input.dispatchMouseEvent', { type: 'mouseWheel', x: 100, y: 200, deltaX: 0, deltaY });
      await waitFor(`document.querySelector(${JSON.stringify(selector)}).querySelector('[data-landing-reveal]').classList.contains('is-visible')`);
      const opacities = await evaluate(`new Promise(resolve => {
        const element = document.querySelector(${JSON.stringify(selector)}).querySelector('[data-landing-reveal]');
        const samples = [];
        const began = performance.now();
        const sample = time => {
          samples.push(Number(getComputedStyle(element).opacity));
          if (time - began < 500) requestAnimationFrame(sample);
          else resolve(samples);
        };
        requestAnimationFrame(sample);
      })`);
      assert.equal(opacities.some(value => value > 0 && value < .99), true, 'Section fades through intermediate frames on wheel scroll: ' + selector);
      await pause(800);
      assert.equal(await evaluate(`getComputedStyle(document.querySelector(${JSON.stringify(selector)}).querySelector('[data-landing-reveal]')).opacity`), '1', 'Section finishes fully visible');
    };
    const assertAnimatedScroll = async selector => {
      const result = await evaluate(`new Promise(resolve => {
        const start = scrollY;
        const link = document.querySelector(${JSON.stringify(selector)});
        link.click();
        const target = document.getElementById(link.hash.slice(1));
        const margin = parseFloat(getComputedStyle(target).scrollMarginTop) || 0;
        const expected = Math.max(0, Math.min(scrollY + target.getBoundingClientRect().top - margin, document.documentElement.scrollHeight - innerHeight));
        const positions = [];
        const began = performance.now();
        const sample = time => {
          positions.push(scrollY);
          if (time - began < 1400) requestAnimationFrame(sample);
          else resolve({
            end: scrollY, expected, hash: location.hash, targetHash: link.hash,
            focused: document.activeElement === target,
            animated: positions.some(y => y > Math.min(start, expected) + 2 && y < Math.max(start, expected) - 2),
          });
        };
        requestAnimationFrame(sample);
      })`);
      assert.equal(result.animated, true, 'Scroll has intermediate animation frames: ' + selector);
      assert.ok(Math.abs(result.end - result.expected) <= 2, 'Scroll reaches its target: ' + selector);
      assert.equal(result.hash, result.targetHash, 'Anchor fragment is preserved');
      assert.equal(result.focused, true, 'Keyboard focus follows the destination');
    };
    const viewport = (width, height, mobile = false) => command('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile });
    const screenshot = async filename => {
      const selection = process.env.UI_SCREENSHOTS;
      if (!selection || (selection !== '1' && !filename.includes(selection))) return;
      const result = await command('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(root, filename), Buffer.from(result.data, 'base64'));
    };
    await command('Page.enable');
    await command('Runtime.enable');
    await command('Page.addScriptToEvaluateOnNewDocument', { source: `
      if (new URLSearchParams(location.search).has('oauth')) localStorage.removeItem('shika_token');
      else localStorage.setItem('shika_token', 'ui-test-token');
      const realFetch = window.fetch.bind(window);
      window.__checkoutCount = 0;
      window.__registrationCount = 0;
      window.__oauthExchangeCount = 0;
      window.fetch = async (input, options = {}) => {
        const url = new URL(typeof input === 'string' ? input : input.url, location.origin);
        let data;
        if (url.pathname === '/auth/register') {
          window.__registrationCount++;
          window.__lastRegistration = JSON.parse(options.body);
          return new Response(JSON.stringify({ status: 'pending', message: 'Account created. Please wait for admin activation before signing in.' }), { status: 201, headers: { 'Content-Type': 'application/json' } });
        }
        else if (url.pathname === '/auth/login') {
          const body = JSON.parse(options.body);
          if (body.password === 'wrong-password') return new Response(JSON.stringify({ detail: 'Invalid credentials' }), { status: 401, headers: { 'Content-Type': 'application/json' } });
          data = { access_token: 'login-ui-token', token_type: 'bearer' };
        }
        else if (url.pathname === '/auth/oauth/session') {
          window.__oauthExchangeCount++;
          data = { access_token: 'oauth-ui-token', token_type: 'bearer' };
        }
        else if (['/auth/oauth/google', '/auth/oauth/discord'].includes(url.pathname)) {
          const provider = url.pathname.endsWith('google') ? 'Google' : 'Discord';
          return new Response(JSON.stringify({ detail: provider + ' OAuth is not configured. Contact the administrator.' }), { status: 501, headers: { 'Content-Type': 'application/json' } });
        }
        else if (url.pathname === '/auth/me') data = { id: 1, full_name: 'Shika Staff', role: 'manager' };
        else if (url.pathname === '/categories') data = ${JSON.stringify(categories)};
        else if (url.pathname === '/products') data = ${JSON.stringify(products)};
        else if (url.pathname === '/menu/products') data = ${JSON.stringify([products[8], products[9], ...products.slice(0, 8)])};
        else if (url.pathname === '/sales/summary/today') data = { order_count: 20 + window.__checkoutCount };
        else if (url.pathname === '/inventory/low-stock') data = [{ id: 1, name: 'Bread', current_stock: '2', unit_symbol: 'pcs' }];
        else if (url.pathname === '/sales' && options.method === 'POST') { window.__checkoutCount++; window.__lastSale = JSON.parse(options.body); data = { id: 1, invoice_number: 'TEST-00001' }; }
        else if (url.pathname === '/sales/1/receipt') data = { store_name: 'Shika Coffee', invoice_number: 'TEST-00001', customer_name: 'Walk-in', cashier: 'Shika Staff', subtotal: 50000, tax: 5000, total_amount: 55000, amount_paid: 60000, change_amount: 5000, payment_method: 'cash', items: [{ name: 'Americano', qty: 2, subtotal: 50000, notes: 'Less sugar' }] };
        else if (url.pathname === '/reports/dashboard') data = { today_revenue: 1250000, today_transactions: 20, low_stock_count: 1, active_products_count: 10 };
        else return realFetch(input, options);
        return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
      };
    ` });
    await viewport(1382, 900);
    await command('Page.navigate', { url: base + '/pos' });
    await waitFor(`window.Alpine && document.querySelectorAll('.pos-product').length === 8 && !document.querySelector('.pos-app')._x_dataStack[0].catalogLoading`);
    await evaluate('document.fonts.ready');
    await pause(400);
    const state = `document.querySelector('.pos-app')._x_dataStack[0]`;
    await assertLogo('.pos-header .pos-brand img');
    assert.match(await evaluate(`document.querySelector('.pos-product-copy p').textContent`), /^Rp\s25\.000$/, 'POS prices use rupiah');
    assert.equal(await evaluate(`document.documentElement.scrollWidth <= innerWidth`), true, 'Desktop must not overflow horizontally');
    assert.equal(await evaluate(`document.querySelector('.pos-checkout').getBoundingClientRect().bottom <= innerHeight`), true, 'Checkout must stay visible');
    assert.equal(await evaluate(`document.querySelector('.pos-checkout').disabled`), true);
    await evaluate(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true, cancelable: true }))`);
    assert.equal(await evaluate(`document.activeElement === document.querySelector('.pos-search input')`), true, 'Ctrl+K focuses menu search');
    await evaluate(`document.activeElement.blur()`);
    await screenshot('.pos-review-desktop.png');
    await evaluate(`document.querySelector('.pos-add-button').click(); document.querySelector('.pos-add-button').click()`);
    await pause(80);
    assert.equal(await evaluate(`${state}.totalCartItems()`), 2);
    assert.equal(await evaluate(`${state}.cartTotal()`), 55000);
    assert.match(await evaluate(`document.querySelector('.pos-checkout-total').textContent`), /^Rp\s55\.000$/, 'Checkout total uses rupiah');
    assert.equal(await evaluate(`document.querySelector('.pos-checkout').disabled`), false);
    await evaluate(`const input = document.querySelector('.pos-search input'); input.value = 'capp'; input.dispatchEvent(new Event('input', { bubbles: true }))`);
    await pause(80);
    assert.equal(await evaluate(`document.querySelectorAll('.pos-product').length`), 1);
    await evaluate(`${state}.searchQuery = ''; ${state}.selectCategory(3)`);
    await pause(80);
    assert.equal(await evaluate(`document.querySelector('.pos-category:last-child .pos-stock-badge').textContent.includes('Need to re-stock')`), true);
    await evaluate(`${state}.selectCategory(1); document.querySelector('.pos-collapse-order').click()`);
    await pause(80);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.pos-order')).display`), 'none');
    await evaluate(`document.querySelector('.pos-reopen-order').click(); ${state}.cart[0].notes = 'Less sugar'; ${state}.paymentMethod = 'cash'; ${state}.amountPaid = '60000'`);
    await pause(80);
    await screenshot('.pos-review-cart.png');
    await evaluate(`document.querySelector('.pos-checkout').click()`);
    await waitFor(`${state}.receiptModal !== null && !${state}.loading`);
    assert.equal(await evaluate(`window.__checkoutCount`), 1);
    assert.equal(await evaluate(`window.__lastSale.items[0].notes`), 'Less sugar');
    assert.equal(await evaluate(`window.__lastSale.amount_paid`), '60000.00', 'Rupiah formatting does not change checkout amounts');
    assert.equal(await evaluate(`${state}.orderCount`), 21);
    assert.equal(await evaluate(`document.querySelector('.pos-receipt-overlay').getAttribute('aria-modal')`), 'true');
    assert.match(await evaluate(`document.querySelector('.pos-receipt-card .pos-grand-total dd').textContent`), /^Rp\s55\.000$/, 'Receipt uses rupiah');
    await screenshot('.pos-review-receipt.png');
    await command('Emulation.setEmulatedMedia', { media: 'print' });
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.pos-workspace')).display`), 'none');
    assert.notEqual(await evaluate(`getComputedStyle(document.querySelector('.pos-receipt-card')).display`), 'none');
    await command('Emulation.setEmulatedMedia', { media: 'screen' });
    await evaluate(`${state}.receiptModal = null`);
    for (const [width, height] of [[1024, 768], [768, 1024], [390, 844], [320, 740]]) {
      await viewport(width, height, width < 701);
      await pause(100);
      assert.equal(await evaluate(`document.documentElement.scrollWidth <= innerWidth`), true, 'POS overflow at ' + width);
      await assertLogo('.pos-header .pos-brand img');
      if (width > 700) {
        assert.equal(await evaluate(`document.querySelector('.pos-checkout').getBoundingClientRect().bottom <= innerHeight`), true, 'Checkout clipped at ' + width);
        assert.equal(await evaluate(`document.querySelector('.pos-order-body').getBoundingClientRect().height >= 85`), true, 'Cart list needs usable scroll space at ' + width);
      }
      if (width === 390) await screenshot('.pos-review-mobile.png');
    }
    await viewport(1382, 900);
    await evaluate(`${state}.logout()`);
    await pause(80);
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.pos-workspace')).display`), 'none');
    assert.notEqual(await evaluate(`getComputedStyle(document.querySelector('.pos-login')).display`), 'none');
    await screenshot('.pos-review-login.png');
    await assertLogo('.pos-login-brand img');
    await screenshot('.logo-review-login.png');
    await screenshot('.auth-review-login-desktop.png');
    assert.equal(await evaluate(`document.querySelectorAll('.pos-auth-panel-inner form').length`), 2, 'Both auth forms stay inside the right panel');
    await evaluate(`document.querySelector('[aria-controls="login-password"]').click()`);
    assert.equal(await evaluate(`document.querySelector('#login-password').type`), 'text');
    await evaluate(`document.querySelector('.pos-auth-switch button').click()`);
    await pause(80);
    assert.equal(await evaluate(`${state}.authMode`), 'register');
    assert.equal(await evaluate(`document.activeElement.id`), 'login-heading');
    assert.equal(await evaluate(`document.querySelector('#register-password').type`), 'password');
    await screenshot('.auth-review-register-desktop.png');
    await evaluate(`${state}.registerForm = { full_name: 'Hana Shika', email: 'hana@example.com', username: 'hana', password: 'password123', confirm_password: 'different123' }`);
    await pause(80);
    await evaluate(`document.querySelector('#register-form').requestSubmit()`);
    await waitFor(`${state}.authError.includes('match')`);
    assert.equal(await evaluate('window.__registrationCount'), 0, 'Password mismatch is caught before submitting');
    await evaluate(`${state}.registerForm.confirm_password = 'password123'`);
    await pause(80);
    await evaluate(`document.querySelector('#register-form').requestSubmit()`);
    await waitFor(`${state}.authMode === 'login' && ${state}.authMessage.includes('admin activation')`);
    assert.equal(await evaluate('window.__registrationCount'), 1);
    assert.deepEqual(await evaluate(`Object.keys(window.__lastRegistration).sort()`), ['email', 'full_name', 'password', 'username']);
    assert.equal(await evaluate(`${state}.token`), '', 'Registration does not grant POS access');
    await evaluate(`document.querySelector('[aria-label="Continue with Google"]').click()`);
    await waitFor(`${state}.authError.includes('Google OAuth is not configured') && !${state}.oauthLoading`);
    await evaluate(`document.querySelector('[aria-label="Continue with Discord"]').click()`);
    await waitFor(`${state}.authError.includes('Discord OAuth is not configured') && !${state}.oauthLoading`);
    for (const [width, height] of [[1382, 900], [1024, 768], [768, 1024], [390, 844], [320, 740]]) {
      await viewport(width, height, width < 801);
      for (const mode of ['login', 'register']) {
        await evaluate(`${state}.setAuthMode('${mode}')`);
        await pause(80);
        await assertLogo('.pos-login-brand img');
        assert.equal(await evaluate(`document.documentElement.scrollWidth <= innerWidth`), true, 'Auth overflow in ' + mode + ' at ' + width);
        assert.equal(await evaluate(`Array.from(document.querySelectorAll('#${mode}-form input')).every(input => input.getBoundingClientRect().left >= 0 && input.getBoundingClientRect().right <= innerWidth)`), true, 'Auth fields remain accessible at ' + width);
        if (width === 390 && mode === 'register') {
          await evaluate(`document.querySelector('.pos-auth-panel').scrollIntoView({ behavior: 'instant', block: 'start' })`);
          await screenshot('.auth-review-register-mobile.png');
        }
      }
    }
    await viewport(1382, 900);
    await evaluate(`${state}.setAuthMode('login'); ${state}.loginForm = { identifier: 'hana@example.com', password: 'wrong-password' }`);
    await pause(80);
    await evaluate(`document.querySelector('#login-form').requestSubmit()`);
    await waitFor(`${state}.authError === 'Invalid credentials'`);
    await evaluate(`${state}.loginForm.password = 'password123'`);
    await pause(80);
    await evaluate(`document.querySelector('#login-form').requestSubmit()`);
    await waitFor(`${state}.token === 'login-ui-token' && !${state}.loading && document.querySelectorAll('.pos-product').length === 8`);
    await command('Page.navigate', { url: base + '/pos?oauth=success' });
    await waitFor(`${state}.token === 'oauth-ui-token' && !${state}.loading && document.querySelectorAll('.pos-product').length === 8`);
    assert.equal(await evaluate('window.__oauthExchangeCount'), 1);
    assert.equal(await evaluate('location.search'), '', 'OAuth feedback is removed from browser history');
    await command('Page.navigate', { url: base + '/pos?oauth=pending' });
    await waitFor(`${state}.authMessage.includes('admin activation')`);
    assert.equal(await evaluate(`${state}.token`), '');
    assert.equal(await evaluate('window.__oauthExchangeCount'), 0, 'Pending OAuth accounts cannot exchange credentials');
    console.log('PASS: POS workflow plus split-screen login/registration, validation, password visibility, social feedback, OAuth handoff, and responsive auth layouts');

    await command('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
    await viewport(1568, 1019);
    await command('Page.navigate', { url: base + '/' });
    await waitFor(`document.querySelectorAll('.landing-product').length === 4`);
    await evaluate('document.fonts.ready');
    await pause(300);
    assert.equal(await evaluate(`document.documentElement.scrollWidth <= innerWidth`), true);
    assert.equal(await evaluate(`document.querySelector('.landing-hero-actions a').getAttribute('href')`), '#menu');
    await assertLogo('.landing-brand img');
    await screenshot('.logo-review-landing.png');
    await screenshot('.landing-review-desktop.png');
    assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('.landing-product-name'), element => element.textContent)`), ['Americano', 'Cappuccino', 'Espresso', 'Flat White']);
    assert.match(await evaluate(`document.querySelector('.landing-product-price').textContent`), /^Rp\s25\.000$/, 'Public menu uses rupiah');
    assert.equal(await evaluate(`document.querySelectorAll('.landing-tagline-last .landing-beans-icon').length`), 1, 'Coffee beans sit beside the final tagline');
    assert.equal(await evaluate(`document.querySelectorAll('.landing-product button, .landing-product a, .landing-product form').length`), 0, 'Showcase remains read-only');
    assert.equal(await evaluate(`document.querySelector('#menu').textContent.includes('Browsing only')`), false, 'Removed browsing disclaimer stays absent');
    assert.equal(await evaluate(`getComputedStyle(document.documentElement).scrollBehavior`), 'smooth');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.landing-back-to-top')).borderTopWidth`), '0px', 'Back-to-top retains its original plain-link appearance');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.landing-back-to-top')).borderRadius`), '0px');
    await assertSectionReveal('#story');
    await assertSectionReveal('#story', true);
    await assertSectionReveal('#menu');
    await assertSectionReveal('#contact');
    await assertAnimatedScroll('.landing-hero-actions a[href="#menu"]');
    await evaluate(`window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' })`);
    await assertAnimatedScroll('.landing-back-to-top');
    await evaluate(`window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' }); document.querySelector('.landing-back-to-top').click()`);
    await pause(150);
    const interruptedPosition = await evaluate(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); scrollY`);
    await pause(1200);
    assert.equal(await evaluate('scrollY'), interruptedPosition, 'User input cancels an in-progress scroll');
    assert.equal(await evaluate(`document.querySelector('#story svg[role="img"] title')?.textContent.includes('Shika')`), true, 'Story includes an accessible deer illustration');
    await evaluate(`document.querySelector('#story').scrollIntoView({ behavior: 'instant', block: 'center' })`);
    await waitFor(`document.querySelector('#story [data-landing-reveal]')?.classList.contains('is-visible')`);
    assert.notEqual(await evaluate(`getComputedStyle(document.querySelector('.landing-story-steam')).animationName`), 'none');
    assert.equal(await evaluate(`parseFloat(getComputedStyle(document.querySelector('.landing-story-copy')).marginTop) >= 24`), true, 'Story copy needs breathing room below its heading');
    assert.equal(await evaluate(`document.querySelectorAll('.landing-story-art figcaption, .landing-contact-art figcaption').length`), 0, 'Removed illustration captions stay absent');
    await pause(750);
    await screenshot('.landing-review-story.png');
    await evaluate(`document.querySelector('#menu').scrollIntoView({ behavior: 'instant', block: 'center' })`);
    await waitFor(`Array.from(document.querySelectorAll('.landing-product')).every(element => element.classList.contains('is-visible'))`);
    await pause(1000);
    await screenshot('.landing-review-menu.png');
    await screenshot('.rupiah-review-menu.png');
    const cardPosition = await evaluate(`(() => { const rect = document.querySelector('.landing-product-image').getBoundingClientRect(); return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }; })()`);
    await command('Input.dispatchMouseEvent', { type: 'mouseMoved', ...cardPosition });
    await pause(450);
    assert.notEqual(await evaluate(`getComputedStyle(document.querySelector('.landing-product article')).transform`), 'none', 'Coffee cards lift on hover');
    await command('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 0, y: 0 });
    await evaluate(`document.querySelector('#contact').scrollIntoView({ behavior: 'instant', block: 'center' })`);
    await waitFor(`document.querySelector('.landing-contact-art').classList.contains('is-visible')`);
    assert.equal(await evaluate(`document.querySelector('#contact svg[role="img"] title')?.textContent.includes('Shika')`), true, 'Contact has an accessible greeting deer');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.landing-contact-wave')).animationName`), 'landing-deer-wave');
    await pause(750);
    await screenshot('.landing-review-contact.png');
    for (const [width, height] of [[1568, 1019], [1101, 800], [1024, 768], [900, 900], [768, 1024], [760, 900], [390, 844], [320, 740]]) {
      await viewport(width, height, width < 761);
      await pause(100);
      assert.equal(await evaluate(`document.documentElement.scrollWidth <= innerWidth`), true, 'Landing overflow at ' + width);
      await assertLogo('.landing-brand img');
      assert.equal(await evaluate(`(() => {
        const icon = document.querySelector('.landing-beans-icon').getBoundingClientRect();
        const item = document.querySelector('.landing-tagline-last').getBoundingClientRect();
        return icon.width > 0 && icon.left >= item.left && icon.right <= item.right + 1 && icon.right <= innerWidth;
      })()`), true, 'Coffee bean icon remains visible at ' + width);
      assert.equal(await evaluate(`(() => {
        const heading = document.querySelector('#landing-menu-heading').getBoundingClientRect();
        const description = document.querySelector('.landing-section-heading > p').getBoundingClientRect();
        const headingFits = heading.right <= innerWidth && heading.left >= 0;
        return headingFits && description.top >= heading.bottom
          && Math.abs(description.left - heading.left) <= 1;
      })()`), true, 'Menu description must stay below and left-aligned with its heading at ' + width);
      assert.equal(await evaluate(`(() => {
        const art = document.querySelector('.landing-contact-art').getBoundingClientRect();
        const content = document.querySelector('.landing-contact-content').getBoundingClientRect();
        return art.left >= 0 && art.right <= innerWidth && (art.top >= content.bottom - 1 || art.left >= content.right);
      })()`), true, 'Contact deer stays separate from its copy at ' + width);
      if (width === 390) {
        await evaluate(`document.querySelector('#contact').scrollIntoView({ behavior: 'instant', block: 'end' })`);
        await pause(150);
        await screenshot('.landing-review-contact-mobile.png');
        await evaluate(`document.querySelector('[data-landing-nav-toggle]').click()`);
        assert.equal(await evaluate(`document.querySelector('[data-landing-nav-toggle]').getAttribute('aria-expanded')`), 'true');
        await assertAnimatedScroll('[data-landing-navigation] a');
        assert.equal(await evaluate(`document.querySelector('[data-landing-nav-toggle]').getAttribute('aria-expanded')`), 'false');
        await evaluate(`window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' })`);
        await assertAnimatedScroll('.landing-back-to-top');
        await screenshot('.landing-review-mobile.png');
      }
    }
    await command('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
    await waitFor(`window.matchMedia('(prefers-reduced-motion: reduce)').matches`);
    assert.equal(await evaluate(`getComputedStyle(document.documentElement).scrollBehavior`), 'auto');
    assert.equal(await evaluate(`window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' }); document.querySelector('.landing-back-to-top').click(); scrollY`), 0, 'Reduced motion returns to top immediately');
    assert.equal(await evaluate(`document.activeElement.id`), 'top');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.landing-story-steam')).animationName`), 'none');
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.landing-contact-wave')).animationName`), 'none', 'Reduced motion disables the greeting wave');
    assert.equal(await evaluate(`Array.from(document.querySelectorAll('[data-landing-reveal]')).every(element => getComputedStyle(element).opacity === '1' && getComputedStyle(element).transform === 'none')`), true, 'Reduced motion leaves all content visible');
    console.log('PASS: Repeatable section reveals on wheel scrolling in both directions, plain footer link, smooth anchors, focus, reduced motion, and responsive layouts');
    await viewport(1382, 900);
    await command('Page.navigate', { url: base + '/reports-page' });
    await waitFor(`document.querySelector('[x-data="shikaReports()"]')?._x_dataStack?.[0].dashboard.today_revenue === 1250000`);
    await pause(80);
    assert.match(await evaluate(`document.querySelector('[x-text="formatMoney(dashboard.today_revenue || 0)"]').textContent`), /^Rp\s1\.250\.000$/, 'Report revenue uses rupiah');
    console.log('PASS: IDR formatting across menu, POS, checkout, receipt, and reports without converting stored amounts');
    assert.deepEqual(exceptions, [], 'Browser JavaScript exceptions');
    console.log('PASS: No uncaught browser JavaScript exceptions');
  } finally {
    if (command && socket?.readyState === WebSocket.OPEN) await command('Browser.close').catch(() => {});
    socket?.close();
    chrome.kill();
    await pause(500);
    try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3, retryDelay: 300 }); } catch { /* Windows may still be releasing Chrome's cache. */ }
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
