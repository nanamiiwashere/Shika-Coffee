// Shared API helper & client logic for Shika Coffee UI
const shikaRupiahFormatter = new Intl.NumberFormat('id-ID', {
  style: 'currency',
  currency: 'IDR',
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

window.shikaFormatMoney = function shikaFormatMoney(value) {
  return shikaRupiahFormatter.format(Number(value || 0));
};

function formatApiError(data, status) {
  const detail = data?.detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((err) => {
      if (typeof err === 'string') return err;
      const loc = Array.isArray(err?.loc) ? err.loc.filter((p) => p !== 'body').join('.') : '';
      return loc ? `${loc}: ${err?.msg || 'Invalid value'}` : (err?.msg || JSON.stringify(err));
    });
    return msgs.join('; ') || `Request failed (${status})`;
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail);
  return detail || `Request failed (${status})`;
}

window.shikaFetch = async function shikaFetch(path, options = {}) {
  const { onAuthError, token: optToken, headers: optHeaders, ...fetchOpts } = options;
  const token = optToken !== undefined ? optToken : (localStorage.getItem('shika_token') || '');
  const headers = { 'Content-Type': 'application/json', ...(optHeaders || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(path, { ...fetchOpts, headers });
  let data = null;
  if (res.status !== 204) {
    const raw = await res.text();
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        data = { detail: raw };
      }
    }
  }

  const isLogin = path === '/auth/login';
  const isMe = path === '/auth/me';
  if ((res.status === 401 && !isLogin) || (res.status === 403 && isMe)) {
    localStorage.removeItem('shika_token');
    if (typeof onAuthError === 'function') onAuthError(res.status);
    const msg = res.status === 401
      ? 'Session expired. Please sign in again.'
      : formatApiError(data, res.status);
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }

  if (!res.ok) {
    const err = new Error(formatApiError(data, res.status));
    err.status = res.status;
    throw err;
  }
  return data;
};

function shikaAuthRequest(path, options = {}) {
  return window.shikaFetch(path, { ...options, token: '', credentials: 'same-origin' });
}

function shikaHomeForRole(role) {
  return ['admin', 'manager'].includes(role) ? '/dashboard' : '/pos';
}

function shikaJwtRoleHint(token) {
  try {
    const parts = String(token || '').split('.');
    if (parts.length < 2) return '';
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const pad = b64.length % 4 ? '='.repeat(4 - (b64.length % 4)) : '';
    const payload = JSON.parse(atob(b64 + pad));
    return typeof payload?.role === 'string' ? payload.role : '';
  } catch {
    return '';
  }
}

function shikaAuth(initialMode = 'login') {
  return {
    authMode: initialMode === 'register' ? 'register' : 'login',
    loading: false,
    oauthLoading: '',
    authError: '',
    authMessage: '',
    showPassword: false,
    showConfirmPassword: false,
    loginForm: { identifier: '', password: '' },
    registerForm: { full_name: '', email: '', username: '', password: '', confirm_password: '' },

    async init() {
      const url = new URL(window.location.href);
      const outcome = url.searchParams.get('oauth');
      if (outcome) {
        url.searchParams.delete('oauth');
        window.history.replaceState(null, '', url.pathname + url.search + url.hash);
        if (outcome === 'success') {
          localStorage.removeItem('shika_token');
          this.loading = true;
          try {
            const res = await shikaAuthRequest('/auth/oauth/session', { method: 'POST' });
            await this.completeSignIn(res.access_token, res.role);
            return;
          } catch (err) {
            this.authError = err.message || 'Social sign-in expired. Please try again.';
          } finally {
            this.loading = false;
          }
          return;
        }
        if (outcome === 'pending') this.authMessage = 'Your account is ready and awaiting admin activation. Please ask your administrator to approve access.';
        else if (outcome === 'cancelled') this.authMessage = 'Social sign-in was cancelled. You can try again whenever you’re ready.';
        else this.authError = 'We couldn’t complete social sign-in. Please try again or sign in with your password.';
        return;
      }

      const existing = localStorage.getItem('shika_token');
      if (existing) {
        try {
          const me = await window.shikaFetch('/auth/me', { token: existing });
          window.location.replace(shikaHomeForRole(me?.role));
        } catch {
          localStorage.removeItem('shika_token');
        }
      }
    },

    async completeSignIn(accessToken, roleHint = '') {
      if (typeof accessToken !== 'string' || !accessToken.trim()) {
        throw new Error('The sign-in response was invalid. Please try again.');
      }
      localStorage.setItem('shika_token', accessToken);
      const role = roleHint || shikaJwtRoleHint(accessToken);
      if (role) {
        window.location.replace(shikaHomeForRole(role));
        return;
      }
      let dest = '/pos';
      try {
        const me = await window.shikaFetch('/auth/me', { token: accessToken });
        dest = shikaHomeForRole(me?.role);
      } catch {}
      window.location.replace(dest);
    },

    async login() {
      if (this.loading || this.oauthLoading) return;
      this.loading = true;
      this.authError = '';
      this.authMessage = '';
      try {
        const res = await shikaAuthRequest('/auth/login', {
          method: 'POST',
          body: JSON.stringify({ identifier: this.loginForm.identifier.trim(), password: this.loginForm.password }),
        });
        this.loginForm.password = '';
        await this.completeSignIn(res.access_token, res.role);
      } catch (err) {
        this.authError = err.message || 'We couldn’t sign you in. Please try again.';
      } finally {
        this.loading = false;
      }
    },

    async register() {
      if (this.loading || this.oauthLoading) return;
      this.authError = '';
      this.authMessage = '';
      if (this.registerForm.password !== this.registerForm.confirm_password) {
        this.authError = 'Your passwords don’t match. Please enter the same password twice.';
        return;
      }
      this.loading = true;
      try {
        const { full_name, email, username, password } = this.registerForm;
        const res = await shikaAuthRequest('/auth/register', {
          method: 'POST',
          body: JSON.stringify({ full_name: full_name.trim(), email: email.trim(), username: username.trim(), password }),
        });
        this.registerForm = { full_name: '', email: '', username: '', password: '', confirm_password: '' };
        this.authMessage = res.message || 'Account created. Please wait for admin activation before signing in.';
      } catch (err) {
        this.authError = err.message || 'We couldn’t create your account. Please try again.';
      } finally {
        this.registerForm.password = '';
        this.registerForm.confirm_password = '';
        this.loading = false;
      }
    },

    async startOAuth(provider) {
      if (this.loading || this.oauthLoading || !['google', 'discord'].includes(provider)) return;
      this.oauthLoading = provider;
      this.authError = '';
      this.authMessage = '';
      try {
        const res = await shikaAuthRequest(`/auth/oauth/${provider}?mode=json&flow=browser`);
        const url = new URL(res.authorize_url);
        const expectedOrigin = provider === 'google' ? 'https://accounts.google.com' : 'https://discord.com';
        if (url.origin !== expectedOrigin) throw new Error('Invalid sign-in destination. Please contact your administrator.');
        window.location.assign(url.href);
      } catch (err) {
        this.authError = err.message || 'Social sign-in is unavailable right now. Please try again.';
        this.oauthLoading = '';
      }
    },
  };
}

function shikaWorkspaceShell() {
  return {
    token: localStorage.getItem('shika_token') || '',
    user: null,
    loading: false,
    toast: { show: false, message: '', type: 'success' },
    _toastTimer: null,
    lowStockItems: [],
    sidebarOpen: false,
    menuOpen: false,
    modeOpen: false,
    notificationsOpen: false,
    receiptModal: null,
    printPopup: { show: false, invoice: '' },
    _printPopupTimer: null,
    profileModalOpen: false,
    profileTab: 'profile',
    profileSaving: false,
    avatarUploading: false,
    authActionBusy: false,
    profileError: '',
    profileForm: { full_name: '', email: '', username: '', avatar_url: '', current_password: '', new_password: '', confirm_password: '' },
    todayFormatted: new Date().toLocaleDateString('en-US', { weekday: 'long', day: 'numeric', month: 'short' }),
    todayMonoDate: new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
    formatMoney: window.shikaFormatMoney,

    notify(message, type = 'success') {
      this.toast = { show: true, message, type };
      if (this._toastTimer) clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => { this.toast.show = false; }, 3200);
    },

    shortInvoice(inv) {
      return String(inv || '').replace(/^INV-\d{8}-/, '#');
    },

    formatCountdown(seconds) {
      const secs = Math.max(0, Math.ceil(Number(seconds || 0)));
      const mins = Math.floor(secs / 60);
      const rem = secs % 60;
      return `${String(mins).padStart(2, '0')}:${String(rem).padStart(2, '0')}`;
    },

    showPrintPopup(invoiceNumber = '') {
      const label = invoiceNumber ? this.shortInvoice(invoiceNumber) : '';
      if (this._printPopupTimer) clearTimeout(this._printPopupTimer);
      this.printPopup = { show: true, invoice: label };
      this._printPopupTimer = setTimeout(() => {
        this.printPopup = { ...this.printPopup, show: false };
      }, 3600);
    },

    dismissPrintPopup() {
      if (this._printPopupTimer) clearTimeout(this._printPopupTimer);
      this.printPopup = { ...this.printPopup, show: false };
    },

    triggerReceiptPrint(invoiceNumber = '') {
      if (typeof window !== 'undefined' && typeof window.print === 'function') {
        window.print();
      }
      this.showPrintPopup(invoiceNumber);
    },

    async api(path, options = {}) {
      return window.shikaFetch(path, {
        ...options,
        token: this.token,
        onAuthError: () => this.logout(),
      });
    },

    async loadStock() {
      const rows = await this.api('/inventory/low-stock');
      if (this.token) this.lowStockItems = rows;
    },

    isManager() {
      return ['admin', 'manager'].includes(this.user?.role);
    },

    isAdmin() {
      return this.user?.role === 'admin';
    },

    userInitials(name) {
      const parts = String(name || 'S').trim().split(/\s+/).filter(Boolean);
      if (parts.length === 0) return 'S';
      return (parts.length === 1 ? parts[0].slice(0, 2) : (parts[0][0] + parts[parts.length - 1][0])).toUpperCase();
    },

    liveQueueCount() {
      return 0;
    },

    lowStockBadgeCount() {
      if (Array.isArray(this.lowStockRows)) return this.lowStockRows.length;
      return Array.isArray(this.lowStockItems) ? this.lowStockItems.length : 0;
    },

    openProfileSettings(initialTab = 'profile') {
      this.sidebarOpen = false;
      this.profileTab = initialTab;
      this.profileError = '';
      this.profileForm = {
        full_name: this.user?.full_name || '',
        email: this.user?.email || '',
        username: this.user?.username || '',
        avatar_url: this.user?.avatar_url || '',
        current_password: '',
        new_password: '',
        confirm_password: '',
      };
      this.profileModalOpen = true;
    },

    closeProfileSettings() {
      this.profileModalOpen = false;
      this.profileError = '';
      this.profileForm.current_password = '';
      this.profileForm.new_password = '';
      this.profileForm.confirm_password = '';
    },

    connectedOAuthEmail(provider) {
      const list = Array.isArray(this.user?.oauth_accounts) ? this.user.oauth_accounts : [];
      const found = list.find(a => a.provider === provider);
      return found ? (found.provider_email || provider) : '';
    },

    isOAuthConfigured(provider) {
      const list = Array.isArray(this.user?.available_oauth_providers) ? this.user.available_oauth_providers : [];
      return list.includes(provider);
    },

    canRemoveAuthMethod() {
      const methods = Array.isArray(this.user?.auth_methods) ? this.user.auth_methods : [];
      return methods.length > 1;
    },

    _readLocalImageFile(file) {
      return new Promise((resolve, reject) => {
        if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
          reject(new Error('Please select a PNG, JPEG, or WebP image.'));
          return;
        }
        if (file.size > 2 * 1024 * 1024) {
          reject(new Error('Image file must be under 2 MB.'));
          return;
        }
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(new Error('Could not read the selected image file.'));
        reader.readAsDataURL(file);
      });
    },

    async uploadProfileAvatar(event) {
      const file = event?.target?.files?.[0];
      if (event?.target) event.target.value = '';
      if (!file) return;
      this.profileError = '';
      this.avatarUploading = true;
      try {
        const imageData = await this._readLocalImageFile(file);
        const updated = await this.api('/auth/me/avatar', {
          method: 'POST',
          body: JSON.stringify({ image_data: imageData }),
        });
        if (!this.token) return;
        this.user = updated;
        this.profileForm.avatar_url = updated.avatar_url || '';
        this.notify('Profile photo updated.');
      } catch (err) {
        if (this.token) this.profileError = err.message || 'Could not upload profile photo.';
      } finally {
        this.avatarUploading = false;
      }
    },

    async removeProfileAvatar() {
      if (this.profileSaving || this.avatarUploading) return;
      this.profileError = '';
      this.profileSaving = true;
      try {
        const updated = await this.api('/auth/me', {
          method: 'PATCH',
          body: JSON.stringify({ avatar_url: '' }),
        });
        if (!this.token) return;
        this.user = updated;
        this.profileForm.avatar_url = '';
        this.notify('Profile photo removed.');
      } catch (err) {
        if (this.token) this.profileError = err.message || 'Could not remove profile photo.';
      } finally {
        this.profileSaving = false;
      }
    },

    async saveProfileSettings() {
      if (this.profileSaving) return;
      this.profileError = '';
      const f = this.profileForm;
      const fullName = String(f.full_name || '').trim();
      const email = String(f.email || '').trim().toLowerCase();
      const username = String(f.username || '').trim();
      if (!fullName) {
        this.profileError = 'Full name is required.';
        return;
      }
      if (!email || !email.includes('@')) {
        this.profileError = 'A valid email address is required.';
        return;
      }
      if (username && /[\s@]/.test(username)) {
        this.profileError = 'Username cannot contain spaces or @.';
        return;
      }

      const payload = { full_name: fullName, email };
      if (username) payload.username = username;

      this.profileSaving = true;
      try {
        const updated = await this.api('/auth/me', {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
        if (!this.token) return;
        this.user = updated;
        this.profileForm.full_name = updated.full_name || '';
        this.profileForm.email = updated.email || '';
        this.profileForm.username = updated.username || '';
        this.profileForm.avatar_url = updated.avatar_url || '';
        this.notify('Profile settings saved.');
      } catch (err) {
        if (this.token) this.profileError = err.message || 'Could not update profile settings.';
      } finally {
        this.profileSaving = false;
      }
    },

    async savePasswordChange() {
      if (this.profileSaving) return;
      this.profileError = '';
      const f = this.profileForm;
      if (!f.new_password || f.new_password.length < 8) {
        this.profileError = 'New password must be at least 8 characters.';
        return;
      }
      if (f.new_password !== f.confirm_password) {
        this.profileError = 'New password and confirmation do not match.';
        return;
      }
      if (this.user?.has_password && !f.current_password) {
        this.profileError = 'Current password is required.';
        return;
      }

      const payload = { new_password: f.new_password };
      if (f.current_password) payload.current_password = f.current_password;

      this.profileSaving = true;
      try {
        const updated = await this.api('/auth/me', {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
        if (!this.token) return;
        this.user = updated;
        this.profileForm.current_password = '';
        this.profileForm.new_password = '';
        this.profileForm.confirm_password = '';
        this.notify(updated.has_password ? 'Password updated.' : 'Password saved.');
      } catch (err) {
        if (this.token) this.profileError = err.message || 'Could not update password.';
      } finally {
        this.profileSaving = false;
      }
    },

    async removePasswordAuth() {
      if (this.authActionBusy) return;
      this.profileError = '';
      this.authActionBusy = true;
      try {
        const updated = await this.api('/auth/me/password', { method: 'DELETE' });
        if (!this.token) return;
        this.user = updated;
        this.notify('Password sign-in removed.');
      } catch (err) {
        if (this.token) this.profileError = err.message || 'Could not remove password sign-in.';
      } finally {
        this.authActionBusy = false;
      }
    },

    async unlinkOAuthProvider(provider) {
      if (this.authActionBusy) return;
      this.profileError = '';
      this.authActionBusy = true;
      try {
        const updated = await this.api(`/auth/me/oauth/${encodeURIComponent(provider)}`, { method: 'DELETE' });
        if (!this.token) return;
        this.user = updated;
        this.notify(`${provider.charAt(0).toUpperCase() + provider.slice(1)} disconnected.`);
      } catch (err) {
        if (this.token) this.profileError = err.message || `Could not disconnect ${provider}.`;
      } finally {
        this.authActionBusy = false;
      }
    },

    localDateStr(offsetDays = 0) {
      const d = new Date();
      d.setDate(d.getDate() + offsetDays);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    },

    tzOffsetParam() {
      return `tz_offset_minutes=${encodeURIComponent(new Date().getTimezoneOffset())}`;
    },

    formatOrderTime(iso) {
      const d = new Date(iso);
      if (!iso || Number.isNaN(d.getTime())) return '';
      return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    },

    formatDateTime(iso) {
      const d = new Date(iso);
      if (!iso || Number.isNaN(d.getTime())) return '';
      return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
    },

    async _initStaffSession(onReady) {
      if (!this.token) {
        window.location.replace('/login');
        return false;
      }
      try {
        this.user = await this.api('/auth/me');
        if (!this.token) return false;
        await onReady();
        return true;
      } catch (err) {
        if (!this.token) return false;
        this.notify(err.message || 'We couldn’t load your staff session.', 'error');
        return false;
      }
    },

    async _runAction(flag, fn, okMsg) {
      if (this[flag]) return false;
      this[flag] = true;
      try {
        await fn();
        if (okMsg) this.notify(okMsg);
        return true;
      } catch (err) {
        if (this.token) this.notify(err.message || 'Request failed.', 'error');
        return false;
      } finally {
        this[flag] = false;
      }
    },

    productImage(p) {
      const base = (typeof window !== 'undefined' && window.SHIKA_IMG_BASE) || '/static/images';
      const url = typeof p?.image_url === 'string' ? p.image_url.trim() : '';
      if (url.startsWith('/static/images/')) return `${base}/${url.slice('/static/images/'.length)}`;
      if (url.startsWith('/') || /^https?:\/\//i.test(url)) return url;
      return `${base}/product-placeholder.svg`;
    },

    _clearSession() {
      if (this._toastTimer) clearTimeout(this._toastTimer);
      if (this._printPopupTimer) clearTimeout(this._printPopupTimer);
      this.toast = { show: false, message: '', type: 'success' };
      this.printPopup = { show: false, invoice: '' };
      this.token = '';
      this.user = null;
      this.lowStockItems = [];
      this.sidebarOpen = false;
      this.menuOpen = false;
      this.modeOpen = false;
      this.notificationsOpen = false;
      this.receiptModal = null;
      this.profileModalOpen = false;
      this.profileError = '';
      localStorage.removeItem('shika_token');
    },

    logout() {
      this._clearSession();
      window.location.replace('/login');
    },
  };
}

function shikaPos() {
  return {
    ...shikaWorkspaceShell(),
    categories: [],
    allProducts: [],
    products: [],
    selectedCategory: null,
    searchQuery: '',
    _productsAbort: null,
    _productsReqId: 0,
    cart: [],
    orderType: 'dine_in',
    customerName: 'Walk-in',
    tableNumber: 'A1',
    paymentMethod: 'qris',
    amountPaid: '',
    orderCount: 0,
    catalogLoading: false,
    catalogError: '',
    qrisModal: null,
    qrisRemaining: 0,
    qrisNotif: { show: false, amount: 0, customer: '' },
    _qrisTickTimer: null,
    _qrisPollTimer: null,
    _qrisNotifTimer: null,
    _qrisCommitting: false,

    get draftOrderNumber() {
      return '#' + String(this.orderCount + 1).padStart(5, '0');
    },

    async init() {
      const url = new URL(window.location.href);
      const outcome = url.searchParams.get('oauth');
      if (outcome) {
        if (outcome !== 'success') {
          window.location.replace(`/login?oauth=${encodeURIComponent(outcome)}`);
          return;
        }
        url.searchParams.delete('oauth');
        window.history.replaceState(null, '', url.pathname + url.search + url.hash);
        localStorage.removeItem('shika_token');
        this.token = '';
        this.loading = true;
        try {
          const res = await shikaAuthRequest('/auth/oauth/session', { method: 'POST' });
          if (typeof res.access_token !== 'string' || !res.access_token.trim()) {
            throw new Error('The sign-in response was invalid. Please try again.');
          }
          this.token = res.access_token;
          localStorage.setItem('shika_token', this.token);
          const oauthRole = res.role || shikaJwtRoleHint(this.token);
          if (['admin', 'manager'].includes(oauthRole)) {
            window.location.replace('/dashboard');
            return;
          }
          if (await this.bootstrapSession()) {
            if (this.isManager()) {
              window.location.replace('/dashboard');
              return;
            }
            this.notify('Welcome back to Shika');
          }
        } catch {
          window.location.replace('/login?oauth=error');
        } finally {
          this.loading = false;
        }
        return;
      }

      if (!this.token) {
        window.location.replace('/login');
        return;
      }
      await this.bootstrapSession();
    },

    logout() {
      this._stopQrisTimers();
      if (this._qrisNotifTimer) clearTimeout(this._qrisNotifTimer);
      this.qrisModal = null;
      this.qrisNotif = { show: false, amount: 0, customer: '' };
      if (this._productsAbort) {
        this._productsAbort.abort();
        this._productsAbort = null;
      }
      this._clearSession();
      this.cart = [];
      this.categories = [];
      this.allProducts = [];
      this.products = [];
      this.orderCount = 0;
      this.catalogError = '';
      this.searchQuery = '';
      this.selectedCategory = null;
      this.customerName = 'Walk-in';
      this.tableNumber = 'A1';
      this.orderType = 'dine_in';
      this.paymentMethod = 'qris';
      this.amountPaid = '';
      window.location.replace('/login');
    },

    async bootstrapSession() {
      try {
        const [me] = await Promise.all([
          this.api('/auth/me'),
          this.loadCategories(),
          this.loadProducts(),
          this.loadSales(),
          this.loadStock(),
        ]);
        if (!this.token) return false;
        this.user = me;
        this.selectedCategory = this.displayCategories[0]?.id ?? null;
        this.applyFilters();
        return true;
      } catch (err) {
        if (!this.token) return false;
        this.notify(err.message || 'We couldn’t load your staff session.', 'error');
        return false;
      }
    },

    get displayCategories() {
      const groups = [
        { id: 'group-coffee', name: 'Coffee', art: 'beans', match: /(?<!non[- ]?)coffee|espresso/i, categoryIds: [] },
        { id: 'group-noncoffee', name: 'Non-coffee', art: 'tea', match: /non.?coffee|beverage|tea|matcha|milk/i, categoryIds: [] },
        { id: 'group-bites', name: 'Bites', art: 'croissant', match: /bite|snack|food|pastry/i, categoryIds: [] },
      ];
      const extras = [];
      for (const cat of this.categories) {
        const target = groups.find(g => g.match.test(cat.name));
        if (target) target.categoryIds.push(cat.id);
        else extras.push({ id: `cat-${cat.id}`, name: cat.name, art: 'beans', categoryIds: [cat.id] });
      }
      return [...groups.filter(g => g.categoryIds.length > 0), ...extras];
    },

    async loadCategories() {
      this.categories = await this.api('/categories');
    },

    async loadProducts() {
      if (this._productsAbort) this._productsAbort.abort();
      const controller = new AbortController();
      this._productsAbort = controller;
      const reqId = ++this._productsReqId;

      this.catalogLoading = true;
      this.catalogError = '';
      try {
        const rows = await this.api('/products', { signal: controller.signal });
        if (reqId !== this._productsReqId || !this.token) return;
        this.allProducts = rows;
        this.applyFilters();
      } catch (err) {
        if (err.name === 'AbortError') return;
        this.catalogError = err.message;
        this.notify(err.message, 'error');
      } finally {
        if (reqId === this._productsReqId) this.catalogLoading = false;
      }
    },

    _selectedCategoryIds() {
      if (this.selectedCategory === null) return null;
      const card = this.displayCategories.find(c => c.id === this.selectedCategory);
      return card ? card.categoryIds : null;
    },

    applyFilters() {
      const query = this.searchQuery.trim().toLowerCase();
      const catIds = this._selectedCategoryIds();
      this.products = this.allProducts.filter(product =>
        (catIds === null || catIds.includes(product.category_id))
        && (!query || `${product.name} ${product.sku || ''}`.toLowerCase().includes(query))
      );
    },

    selectCategory(catId) {
      this.selectedCategory = catId;
      this.applyFilters();
    },

    categoryLowStock(cat) {
      const ids = cat?.categoryIds || [];
      return this.allProducts.some(product => ids.includes(product.category_id) && product.is_low_stock);
    },

    countByCategory(cat) {
      const ids = cat?.categoryIds || [];
      return this.allProducts.filter(p => ids.includes(p.category_id)).length;
    },

    cartQty(productId) {
      const found = this.cart.find(i => i.product_id === productId);
      return found ? found.quantity : 0;
    },

    addToCart(product) {
      if (this.loading) return;
      const existing = this.cart.find(i => i.product_id === product.id);
      if (existing) {
        existing.quantity += 1;
      } else {
        this.cart.push({ product_id: product.id, name: product.name, price: Number(product.price), image_url: this.productImage(product), quantity: 1, notes: '' });
      }
    },

    changeQty(idx, delta) {
      if (this.loading) return;
      this.cart[idx].quantity += delta;
      if (this.cart[idx].quantity <= 0) this.cart.splice(idx, 1);
    },

    totalCartItems() {
      return this.cart.reduce((sum, i) => sum + i.quantity, 0);
    },

    cartSubtotal() {
      const cents = this.cart.reduce((sum, i) => sum + Math.round(i.price * 100) * i.quantity, 0);
      return cents / 100;
    },

    cartTax() {
      return Math.round(Math.round(this.cartSubtotal() * 100) / 10) / 100;
    },

    cartTotal() {
      return Math.round((this.cartSubtotal() + this.cartTax()) * 100) / 100;
    },

    resolvedAmountPaid() {
      const total = this.cartTotal();
      if (this.paymentMethod !== 'cash' || this.amountPaid === '' || this.amountPaid === null) {
        return total;
      }
      return Math.round(Number(this.amountPaid) * 100) / 100;
    },

    cashChange() {
      if (this.paymentMethod !== 'cash') return 0;
      const diff = Math.round((this.resolvedAmountPaid() - this.cartTotal()) * 100) / 100;
      return diff > 0 ? diff : 0;
    },

    formatMoney: window.shikaFormatMoney,

    _buildCustomerLabel() {
      const baseName = (this.customerName || '').trim() || 'Walk-in';
      const table = this.orderType === 'dine_in' ? (this.tableNumber || '').trim() : '';
      const suffix = table ? ` (Table ${table})` : '';
      return suffix
        ? `${baseName.slice(0, Math.max(1, 50 - suffix.length))}${suffix}`.slice(0, 50)
        : baseName.slice(0, 50);
    },

    _stopQrisTimers() {
      if (this._qrisTickTimer) { clearInterval(this._qrisTickTimer); this._qrisTickTimer = null; }
      if (this._qrisPollTimer) { clearInterval(this._qrisPollTimer); this._qrisPollTimer = null; }
    },

    qrisProgressPct() {
      const total = Number(this.qrisModal?.timeout_seconds || 300);
      if (total <= 0) return 0;
      return Math.max(0, Math.min(100, (this.qrisRemaining / total) * 100));
    },

    showQrisPaidNotif(amount, customer) {
      if (this._qrisNotifTimer) clearTimeout(this._qrisNotifTimer);
      this.qrisNotif = { show: true, amount: Number(amount || 0), customer: customer || 'Walk-in' };
      this._qrisNotifTimer = setTimeout(() => {
        this.qrisNotif = { ...this.qrisNotif, show: false };
      }, 4200);
    },

    async startQrisCheckout() {
      if (!this.cart.length || this.loading) return;
      const total = this.cartTotal();
      const label = this._buildCustomerLabel();
      this._stopQrisTimers();
      this._qrisCommitting = false;
      this.loading = true;
      try {
        const session = await this.api('/sales/qris/sessions', {
          method: 'POST',
          body: JSON.stringify({
            amount: total.toFixed(2),
            customer_name: label,
            timeout_seconds: 300,
          }),
        });
        if (!this.token) return;
        this.qrisModal = session;
        this.qrisRemaining = Number(session.remaining_seconds || 300);
        const deadlineMs = Date.now() + this.qrisRemaining * 1000;

        this._qrisTickTimer = setInterval(() => {
          const left = Math.max(0, (deadlineMs - Date.now()) / 1000);
          this.qrisRemaining = left;
          if (left <= 0 && this.qrisModal && this.qrisModal.status === 'pending') {
            this._stopQrisTimers();
            this.qrisModal = { ...this.qrisModal, status: 'expired' };
          }
        }, 250);

        this._qrisPollTimer = setInterval(async () => {
          if (!this.qrisModal || this.qrisModal.status !== 'pending' || this._qrisCommitting) return;
          try {
            const latest = await this.api(`/sales/qris/sessions/${encodeURIComponent(this.qrisModal.session_id)}`);
            if (!this.qrisModal) return;
            if (latest.status === 'paid') {
              this._qrisCommitting = true;
              this._stopQrisTimers();
              this.qrisModal = { ...this.qrisModal, status: 'paid' };
              this.showQrisPaidNotif(latest.amount, latest.customer_name);
              const committed = await this._submitSaleCheckout();
              if (committed) this.qrisModal = null;
              this._qrisCommitting = false;
            } else if (latest.status === 'expired' || latest.status === 'cancelled') {
              this._stopQrisTimers();
              this.qrisRemaining = 0;
              this.qrisModal = { ...this.qrisModal, status: latest.status };
            }
          } catch {}
        }, 350);
      } catch (err) {
        this.notify(err.message || 'Could not start QRIS payment.', 'error');
      } finally {
        this.loading = false;
      }
    },

    async retryQrisCheckout() {
      await this.startQrisCheckout();
    },

    async cancelQrisCheckout() {
      const active = this.qrisModal;
      this._stopQrisTimers();
      this._qrisCommitting = false;
      this.qrisModal = null;
      this.qrisRemaining = 0;
      if (active?.session_id && active.status === 'pending' && this.token) {
        this.api(`/sales/qris/sessions/${encodeURIComponent(active.session_id)}/cancel`, { method: 'POST' }).catch(() => {});
      }
    },

    async checkout() {
      if (!this.cart.length || this.loading) return;
      if (this.paymentMethod === 'qris') {
        await this.startQrisCheckout();
        return;
      }
      await this._submitSaleCheckout();
    },

    async _submitSaleCheckout() {
      if (!this.cart.length || this.loading) return false;
      const total = this.cartTotal();
      const paid = this.resolvedAmountPaid();
      if (!Number.isFinite(paid) || paid < total) {
        this.notify('Insufficient amount paid', 'error');
        return false;
      }

      this.loading = true;
      try {
        const label = this._buildCustomerLabel();

        const sale = await this.api('/sales', {
          method: 'POST',
          body: JSON.stringify({
            customer_name: label,
            order_type: this.orderType,
            discount: '0.00',
            tax: this.cartTax().toFixed(2),
            payment_method: this.paymentMethod,
            amount_paid: paid.toFixed(2),
            items: this.cart.map(i => ({
              product_id: i.product_id,
              quantity: i.quantity,
              notes: i.notes?.trim() ? i.notes.trim().slice(0, 200) : null,
            }))
          })
        });
        this.cart = [];
        this.customerName = 'Walk-in';
        this.tableNumber = 'A1';
        this.amountPaid = '';
        // The sale is committed; a failed refresh must never invite a second charge.
        try {
          this.receiptModal = await this.api(`/sales/${sale.id}/receipt`);
        } catch {
          this.notify(`Order ${sale.invoice_number} completed, but its receipt could not be loaded. Find it in Reports.`, 'error');
          return true;
        } finally {
          await Promise.allSettled([this.loadSales(), this.loadStock(), this.loadProducts()]);
        }
        this.notify(`Order ${sale.invoice_number} completed!`);
        return true;
      } catch (err) {
        this.notify(err.message, 'error');
        return false;
      } finally {
        this.loading = false;
      }
    },

    async loadSales() {
      const summary = await this.api('/sales/summary/today');
      if (this.token) this.orderCount = summary.order_count;
    }
  };
}

function shikaQrisPayPage(sessionId) {
  return {
    sessionId,
    session: null,
    remaining: 0,
    loading: true,
    paying: false,
    error: '',
    _timer: null,
    formatMoney: window.shikaFormatMoney,

    async init() {
      try {
        const res = await fetch(`/sales/qris/sessions/${encodeURIComponent(this.sessionId)}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          this.error = data.detail || 'QRIS session not found.';
          return;
        }
        this.session = data;
        this.remaining = Number(data.remaining_seconds || 0);
        if (data.status === 'pending' && this.remaining > 0) {
          const deadlineMs = Date.now() + this.remaining * 1000;
          this._timer = setInterval(() => {
            const left = Math.max(0, (deadlineMs - Date.now()) / 1000);
            this.remaining = left;
            if (left <= 0 && this.session && this.session.status === 'pending') {
              clearInterval(this._timer);
              this._timer = null;
              this.session = { ...this.session, status: 'expired' };
            }
          }, 100);
        }
      } catch {
        this.error = 'Could not connect to QRIS payment server.';
      } finally {
        this.loading = false;
      }
    },

    progressPct() {
      const total = Number(this.session?.timeout_seconds || 300);
      if (total <= 0) return 0;
      return Math.max(0, Math.min(100, (this.remaining / total) * 100));
    },

    formatCountdown(seconds) {
      const secs = Math.max(0, Math.ceil(Number(seconds || 0)));
      const mins = Math.floor(secs / 60);
      const rem = secs % 60;
      return `${String(mins).padStart(2, '0')}:${String(rem).padStart(2, '0')}`;
    },

    async submitPay() {
      if (this.paying || !this.session || this.session.status !== 'pending') return;
      this.paying = true;
      this.error = '';
      try {
        const res = await fetch(`/sales/qris/sessions/${encodeURIComponent(this.sessionId)}/pay`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 410) {
          if (this._timer) { clearInterval(this._timer); this._timer = null; }
          this.remaining = 0;
          this.session = { ...this.session, status: 'expired' };
          return;
        }
        if (!res.ok) {
          this.error = data.detail || 'Could not complete QRIS payment.';
          return;
        }
        if (this._timer) { clearInterval(this._timer); this._timer = null; }
        this.session = data;
      } catch {
        this.error = 'Network error while sending QRIS payment.';
      } finally {
        this.paying = false;
      }
    },
  };
}

const SHIKA_BAR_STAGES_KEY = 'shika_bar_stages';
const SHIKA_BAR_STAGE_ORDER = ['queued', 'brewing', 'ready', 'served'];
const SHIKA_DB_TO_STAGE = { received: 'queued', processing: 'brewing', ready: 'ready', finished: 'served' };
const SHIKA_STAGE_TO_DB = { queued: 'received', brewing: 'processing', ready: 'ready', served: 'finished' };

function shikaLocalDateOf(iso) {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function shikaResolveOrderStage(order, localMap, todayStr) {
  if (!order) return 'queued';
  if (order.status === 'cancelled') return 'cancelled';
  const orderDay = shikaLocalDateOf(order.transaction_date);
  if (todayStr && orderDay && orderDay < todayStr) return 'served';
  const dbStage = SHIKA_DB_TO_STAGE[order.order_status];
  if (dbStage && dbStage !== 'queued') return dbStage;
  const localStage = localMap?.[order.id];
  if (SHIKA_BAR_STAGE_ORDER.includes(localStage)) return localStage;
  return 'queued';
}

const SHIKA_KDS_COLUMNS = [
  { id: 'queued', label: 'Queued', subtitle: 'Waiting', icon: 'clock', nextStage: 'brewing', ctaLabel: 'Start Brew', ctaStyle: 'is-surface', emptyText: 'No orders waiting' },
  { id: 'brewing', label: 'Brewing', subtitle: 'On bar', icon: 'flame', nextStage: 'ready', ctaLabel: 'Mark Ready', ctaStyle: 'is-surface', emptyText: 'Nothing brewing on the bar' },
  { id: 'ready', label: 'Ready', subtitle: 'Pickup', icon: 'check-circle', nextStage: 'served', ctaLabel: 'Complete', ctaStyle: 'is-complete', emptyText: 'No orders ready for pickup' },
];

function shikaOrders() {
  return {
    ...shikaWorkspaceShell(),
    todayKdsDate: new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
    queueColumns: SHIKA_KDS_COLUMNS,
    activeView: 'queue',
    activeCategory: null,
    orderTypeFilter: 'all',
    searchQuery: '',
    categories: [],
    productById: {},
    orders: [],
    stageMap: {},
    leavingOrderIds: {},
    enteringOrderIds: {},
    receivingColumn: '',
    historyTabPulse: false,
    _enterTimers: {},
    _colPulseTimer: null,
    _historyPulseTimer: null,
    detailsOrderId: null,
    ordersLoading: false,
    ordersError: '',
    cancellingOrder: false,
    confirmCancelId: null,
    _pollTimer: null,

    get detailsOrder() {
      if (this.detailsOrderId === null) return null;
      return this.orders.find(o => o.id === this.detailsOrderId) || null;
    },

    async init() {
      if (!this.token) {
        window.location.replace('/login');
        return;
      }
      this.stageMap = this._loadStageMap();
      try {
        const [me] = await Promise.all([
          this.api('/auth/me'),
          this.loadCatalogLookups(),
          this.loadOrders(),
          this.loadStock(),
        ]);
        if (!this.token) return;
        this.user = me;
        // ponytail: 15s polling; upgrade to SSE/WebSocket if sub-second kitchen sync across stations is needed.
        this._pollTimer = setInterval(() => {
          if (this.token && !document.hidden && !this.ordersLoading && !this.cancellingOrder) {
            this.loadOrders(true);
          }
        }, 15000);
      } catch (err) {
        if (!this.token) return;
        this.notify(err.message || 'We couldn’t load your staff session.', 'error');
      }
    },

    async loadCatalogLookups() {
      try {
        const [cats, prods] = await Promise.all([
          this.api('/categories'),
          this.api('/products?active_only=false'),
        ]);
        if (!this.token) return;
        this.categories = Array.isArray(cats) ? cats : [];
        const map = {};
        for (const p of (Array.isArray(prods) ? prods : [])) {
          map[p.id] = { category_id: p.category_id, category_name: p.category_name || 'Drink' };
        }
        this.productById = map;
      } catch {}
    },

    async loadOrders(silent = false) {
      if (!silent) this.ordersLoading = true;
      this.ordersError = '';
      try {
        if (this.categories.length === 0) await this.loadCatalogLookups();
        const rows = await this.api('/sales?include_items=true');
        if (!this.token) return;
        const hydrated = (Array.isArray(rows) ? rows : []).map(row => ({ ...row, items: row.items || [] }));
        const today = this.localDateStr(0);
        const nextStages = { ...this._loadStageMap() };
        let changed = false;
        for (const order of hydrated) {
          const resolved = shikaResolveOrderStage(order, nextStages, today);
          if (resolved !== 'cancelled' && nextStages[order.id] !== resolved) {
            nextStages[order.id] = resolved;
            changed = true;
          }
        }
        this.stageMap = nextStages;
        if (changed) this._saveStageMap(nextStages);
        this.orders = hydrated;
      } catch (err) {
        if (!this.token || silent) return;
        this.ordersError = err.message || 'Could not load bar orders.';
      } finally {
        if (!silent) this.ordersLoading = false;
      }
    },

    _loadStageMap() {
      try {
        const raw = JSON.parse(localStorage.getItem(SHIKA_BAR_STAGES_KEY) || '{}');
        if (!raw || typeof raw !== 'object') return {};
        const clean = {};
        for (const [k, v] of Object.entries(raw)) {
          if (SHIKA_BAR_STAGE_ORDER.includes(v)) clean[k] = v;
        }
        return clean;
      } catch {
        return {};
      }
    },

    _saveStageMap(map) {
      try {
        localStorage.setItem(SHIKA_BAR_STAGES_KEY, JSON.stringify(map));
      } catch {}
    },

    orderStage(order) {
      return shikaResolveOrderStage(order, this.stageMap, this.localDateStr(0));
    },

    stageLabel(stageId) {
      const labels = { queued: 'Queued', brewing: 'Brewing', ready: 'Ready', served: 'Served', cancelled: 'Cancelled' };
      return labels[stageId] || 'Queued';
    },

    nextStageOf(stageId) {
      const idx = SHIKA_BAR_STAGE_ORDER.indexOf(stageId);
      return idx >= 0 && idx < SHIKA_BAR_STAGE_ORDER.length - 1 ? SHIKA_BAR_STAGE_ORDER[idx + 1] : null;
    },

    nextCtaLabel(stageId) {
      return { queued: 'Start Brew', brewing: 'Mark Ready', ready: 'Complete' }[stageId] || '';
    },

    _markCardEntering(orderId, targetStage) {
      if (this._enterTimers[orderId]) clearTimeout(this._enterTimers[orderId]);
      this.enteringOrderIds = { ...this.enteringOrderIds, [orderId]: true };
      this._enterTimers[orderId] = setTimeout(() => {
        const next = { ...this.enteringOrderIds };
        delete next[orderId];
        this.enteringOrderIds = next;
        delete this._enterTimers[orderId];
      }, 540);

      if (['brewing', 'ready'].includes(targetStage)) {
        if (this._colPulseTimer) clearTimeout(this._colPulseTimer);
        this.receivingColumn = targetStage;
        this._colPulseTimer = setTimeout(() => {
          this.receivingColumn = '';
          this._colPulseTimer = null;
        }, 540);
      } else if (targetStage === 'served') {
        if (this._historyPulseTimer) clearTimeout(this._historyPulseTimer);
        this.historyTabPulse = true;
        this._historyPulseTimer = setTimeout(() => {
          this.historyTabPulse = false;
          this._historyPulseTimer = null;
        }, 540);
      }
    },

    setOrderStage(order, stage) {
      if (!order || !SHIKA_BAR_STAGE_ORDER.includes(stage)) return;
      if (this.leavingOrderIds[order.id]) return;

      const commit = () => {
        const dbStatus = SHIKA_STAGE_TO_DB[stage];
        if (dbStatus) order.order_status = dbStatus;
        const next = { ...this.stageMap, [order.id]: stage };
        this.stageMap = next;
        this._saveStageMap(next);
        this._markCardEntering(order.id, stage);
        this.notify(`${this.ticketChannel(order)} ${this.shortInvoice(order.invoice_number)} moved to ${this.stageLabel(stage)}.`);
        if (dbStatus && order.status !== 'cancelled') {
          this.api(`/sales/${order.id}/order-status`, {
            method: 'PATCH',
            body: JSON.stringify({ order_status: dbStatus }),
          }).catch(() => {});
        }
      };

      const reducedMotion = typeof window !== 'undefined'
        && typeof window.matchMedia === 'function'
        && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

      if (this.detailsOrderId === order.id || reducedMotion) {
        commit();
        return;
      }

      this.leavingOrderIds = { ...this.leavingOrderIds, [order.id]: stage };
      setTimeout(() => {
        const nextLeaving = { ...this.leavingOrderIds };
        delete nextLeaving[order.id];
        this.leavingOrderIds = nextLeaving;
        commit();
      }, 220);
    },

    _matchesFilters(order) {
      if (!order) return false;
      const type = order.order_type === 'take_away' ? 'take_away' : 'dine_in';
      if (this.orderTypeFilter !== 'all' && type !== this.orderTypeFilter) return false;

      if (this.activeCategory !== null) {
        const hasCat = (order.items || []).some(it => Number(this.itemCategoryId(it)) === Number(this.activeCategory));
        if (!hasCat) return false;
      }

      const q = this.searchQuery.trim().toLowerCase();
      if (!q) return true;
      const itemText = (order.items || [])
        .map(it => `${it.product_name || ''} ${this.itemCategoryName(it)} ${it.notes || ''}`)
        .join(' ');
      const haystack = `${this.ticketChannel(order)} ${this.ticketGuest(order)} ${order.invoice_number || ''} ${this.shortInvoice(order.invoice_number)} ${itemText}`.toLowerCase();
      return haystack.includes(q);
    },

    columnOrders(stageId) {
      const list = this.orders.filter(o => o.status !== 'cancelled' && this.orderStage(o) === stageId && this._matchesFilters(o));
      return list.sort((a, b) => new Date(a.transaction_date) - new Date(b.transaction_date) || Number(a.id) - Number(b.id));
    },

    servedOrders() {
      const list = this.orders.filter(o => (o.status === 'cancelled' || this.orderStage(o) === 'served') && this._matchesFilters(o));
      return list.sort((a, b) => new Date(b.transaction_date) - new Date(a.transaction_date) || Number(b.id) - Number(a.id));
    },

    itemSummaryLine(order) {
      return (order?.items || []).map(it => `${it.quantity}× ${it.product_name}`).join(', ');
    },

    guestOrderCount(order) {
      const name = this.ticketGuest(order).toLowerCase();
      if (!name || name === 'guest' || name === 'walk-in') return 0;
      return this.orders.filter(o => o.status !== 'cancelled' && this.ticketGuest(o).toLowerCase() === name).length;
    },

    async printDetailsReceipt() {
      const order = this.detailsOrder;
      if (!order) return;
      try {
        const receipt = await this.api(`/sales/${order.id}/receipt`);
        if (!this.token) return;
        this.receiptModal = receipt;
        this.$nextTick(() => this.triggerReceiptPrint(receipt?.invoice_number));
      } catch (err) {
        if (this.token) this.notify(err.message || 'Could not load receipt for printing.', 'error');
      }
    },

    queueCount() {
      return ['queued', 'brewing', 'ready'].reduce((sum, st) => sum + this.columnOrders(st).length, 0);
    },

    liveQueueCount() {
      return this.queueCount();
    },

    historyCount() {
      return this.servedOrders().length;
    },

    ticketChannel(order) {
      if (!order) return '';
      if (order.order_type === 'take_away') return 'Takeaway';
      const match = String(order.customer_name || '').match(/\(([^)]+)\)\s*$/);
      return match ? match[1].trim() : 'Dine In';
    },

    ticketGuest(order) {
      if (!order) return '';
      const clean = String(order.customer_name || '').replace(/\s*\([^)]+\)\s*$/, '').trim();
      return clean || 'Guest';
    },

    itemCount(order) {
      return (order?.items || []).reduce((sum, it) => sum + Number(it.quantity || 0), 0);
    },

    itemCategoryId(it) {
      return it?.category_id ?? this.productById[it?.product_id]?.category_id ?? null;
    },

    itemCategoryName(it) {
      return it?.category_name || this.productById[it?.product_id]?.category_name || 'Menu Item';
    },

    orderNotes(order) {
      const itemsWithNotes = (order?.items || []).filter(it => typeof it?.notes === 'string' && it.notes.trim() !== '');
      if (itemsWithNotes.length === 0) return [];
      if (itemsWithNotes.length === 1) return [itemsWithNotes[0].notes.trim()];
      return itemsWithNotes.map(it => `${it.product_name}: ${it.notes.trim()}`);
    },

    shortInvoice(inv) {
      return String(inv || '').replace(/^INV-\d{8}-/, '#');
    },

    formatCountdown(seconds) {
      const secs = Math.max(0, Math.ceil(Number(seconds || 0)));
      const mins = Math.floor(secs / 60);
      const rem = secs % 60;
      return `${String(mins).padStart(2, '0')}:${String(rem).padStart(2, '0')}`;
    },

    openDetails(order) {
      this.confirmCancelId = null;
      this.detailsOrderId = order?.id ?? null;
    },

    closeDetails() {
      this.confirmCancelId = null;
      this.detailsOrderId = null;
    },

    async cancelOrder(order) {
      if (!order || !this.isManager()) return;
      await this._runAction('cancellingOrder', async () => {
        await this.api(`/sales/${order.id}/cancel`, { method: 'POST' });
        const next = { ...this.stageMap };
        delete next[order.id];
        this.stageMap = next;
        this._saveStageMap(next);
        this.closeDetails();
        await Promise.all([this.loadOrders(true), this.loadStock()]);
      }, `Order ${this.shortInvoice(order.invoice_number)} cancelled and stock restored.`);
    },

    logout() {
      if (this._pollTimer) clearInterval(this._pollTimer);
      this._clearSession();
      this.orders = [];
      this.detailsOrderId = null;
      window.location.replace('/login');
    },
  };
}

function shikaReports() {
  const VOID_REASONS_KEY = 'shika_void_reasons';
  const RECIPE_STEPS_KEY = 'shika_recipe_steps';

  return {
    ...shikaWorkspaceShell(),
    activeTab: 'overview',
    accessDenied: false,
    initialLoading: true,
    busy: false,

    // Overview + Live Queue + Charts + Shift Notes
    dashboard: {},
    revFrom: '',
    revTo: '',
    topDays: '30',
    revenueRows: [],
    topProducts: [],
    cogsRows: [],
    todaySales: [],
    chartSales: [],
    chartMetric: 'revenue',
    chartRange: 'today',
    hoveredBarIdx: null,
    queueStageMap: {},
    shiftNotes: [],
    shiftNotesFilter: 'all',
    shiftNoteSaving: false,
    shiftNoteForm: { category: 'flavor', text: '' },

    // Sales & Voids
    sales: [],
    salesStatusTab: 'all',
    salesTenderFilter: '',
    salesSearch: '',
    inspectedSaleId: null,
    voidModalSale: null,
    voidReason: '',
    voidReasonMap: {},
    voidReasonPresets: [
      'Guest changed order before prep',
      'Duplicate POS ring-up',
      'Drink quality / remake refund',
      'Out of ingredient at bar',
    ],

    // Menu & Recipes
    categories: [],
    products: [],
    rawMaterials: [],
    productById: {},
    productSearch: '',
    productCategoryFilter: '',
    selectedProductId: null,
    editingRecipe: false,
    productModalOpen: false,
    productImageUploading: false,
    categoryModalOpen: false,
    catForm: { id: null, name: '', description: '' },
    productForm: { id: null, category_id: '', sku: '', name: '', price: '', image_url: '' },
    recipeProduct: null,
    recipeItems: [],
    recipeAddForm: { raw_material_id: '', quantity_required: '' },
    recipeStepsMap: {},
    methodStepsDraft: '',

    // Roastery & Beans (Inventory Management)
    inventoryRows: [],
    lowStockRows: [],
    suppliers: [],
    units: [],
    roasteryGroupMode: 'item',
    roasteryHoveredKey: null,
    roasterySearch: '',
    restockMaterial: null,
    restockForm: { supplier_id: '', quantity: '', unit_price: '', notes: '' },
    materialModalOpen: false,
    materialImageUploading: false,
    materialForm: { id: null, unit_id: '', sku: '', name: '', minimum_stock: '10', image_url: '' },
    stockActionMaterial: null,
    stockActionMode: 'adjust',
    adjustForm: { actual_stock: '', notes: '' },
    wasteForm: { quantity: '', notes: '' },
    ledgerMaterial: null,
    ledgerMutations: [],
    unitModalOpen: false,
    unitForm: { id: null, name: '', symbol: '' },

    // Purchasing & Suppliers
    purchases: [],
    purchaseSummary: { total_orders: 0, total_spend: 0, active_suppliers: 0 },
    purchasingSubTab: 'pos',
    purchasingSearch: '',
    inspectedPurchase: null,
    poModalOpen: false,
    poForm: { supplier_id: '', notes: '', items: [{ raw_material_id: '', quantity: '', unit_price: '' }] },
    supplierModalOpen: false,
    supplierForm: { id: null, name: '', phone: '', email: '', address: '' },

    // Reports & Analytics
    analyticsPreset: '30d',
    analyticsTopProducts: [],
    analyticsMarginSort: 'profit_desc',
    analyticsMarginSearch: '',

    // Staff Users
    users: [],
    staffStatusTab: 'all',
    staffRoleFilter: '',
    staffSearch: '',
    revealedIdMap: {},
    staffModalOpen: false,
    userForm: { id: null, full_name: '', email: '', username: '', password: '', role: 'cashier', is_active: true },

    get inspectedSale() {
      if (this.inspectedSaleId === null) return null;
      return this.sales.find(s => s.id === this.inspectedSaleId) || null;
    },

    get selectedProduct() {
      if (this.selectedProductId === null) return null;
      return this.products.find(p => p.id === this.selectedProductId) || null;
    },

    async init() {
      this.queueStageMap = this._readJsonStore(SHIKA_BAR_STAGES_KEY);
      // ponytail: client-side void reasons & prep steps stored per browser in localStorage; move to DB columns when multi-device sync is needed.
      this.voidReasonMap = this._readJsonStore(VOID_REASONS_KEY);
      this.recipeStepsMap = this._readJsonStore(RECIPE_STEPS_KEY);

      this.revFrom = this.localDateStr(-29);
      this.revTo = this.localDateStr(0);
      if (typeof window !== 'undefined') {
        const urlTab = new URLSearchParams(window.location.search).get('tab');
        if (['overview', 'sales', 'menu', 'roastery', 'purchasing', 'analytics', 'users'].includes(urlTab)) {
          this.activeTab = urlTab;
        }
      }

      if (!this.token) {
        window.location.replace('/login');
        return;
      }
      const roleHint = shikaJwtRoleHint(this.token);
      try {
        if (['admin', 'manager'].includes(roleHint)) {
          const [meRes, ovRes] = await Promise.allSettled([this.api('/auth/me'), this.loadOverview()]);
          if (!this.token) return;
          if (meRes.status === 'rejected') throw meRes.reason;
          this.user = meRes.value;
          if (!this.isManager()) {
            this.accessDenied = true;
            return;
          }
          await this.loadDashboardBackgroundTabs();
          if (ovRes.status === 'rejected') throw ovRes.reason;
        } else {
          this.user = await this.api('/auth/me');
          if (!this.token) return;
          if (!this.isManager()) {
            this.accessDenied = true;
            return;
          }
          await this.loadDashboardAll();
        }
      } catch (err) {
        if (this.token) this.notify(err.message || 'Could not refresh dashboard data.', 'error');
      } finally {
        this.initialLoading = false;
      }
    },

    _readJsonStore(key) {
      try {
        const raw = JSON.parse(localStorage.getItem(key) || '{}');
        return raw && typeof raw === 'object' ? raw : {};
      } catch {
        return {};
      }
    },

    _writeJsonStore(key, obj) {
      try {
        localStorage.setItem(key, JSON.stringify(obj));
      } catch {}
    },

    shiftNotesByCategory(cat) {
      return (Array.isArray(this.shiftNotes) ? this.shiftNotes : []).filter(n => n.category === cat);
    },

    filteredShiftNotes() {
      const list = Array.isArray(this.shiftNotes) ? this.shiftNotes : [];
      if (this.shiftNotesFilter === 'all') return list;
      return list.filter(n => n.category === this.shiftNotesFilter);
    },

    shiftNoteCategoryLabel(cat) {
      return { flavor: 'Flavor Note', maintenance: 'Maintenance', service: 'Service' }[cat] || 'Flavor Note';
    },

    formatShortAuthor(name) {
      const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
      if (parts.length === 0) return 'Staff';
      if (parts.length === 1) return parts[0];
      return `${parts[0]} ${parts[parts.length - 1][0].toUpperCase()}.`;
    },

    async loadShiftNotes() {
      const rows = await this.api('/reports/shift-notes');
      if (this.token) this.shiftNotes = Array.isArray(rows) ? rows : [];
    },

    async addShiftNote() {
      const content = String(this.shiftNoteForm.text || '').trim();
      if (!content || this.shiftNoteSaving) return;
      const category = ['flavor', 'maintenance', 'service'].includes(this.shiftNoteForm.category)
        ? this.shiftNoteForm.category
        : 'flavor';
      await this._runAction('shiftNoteSaving', async () => {
        const created = await this.api('/reports/shift-notes', {
          method: 'POST',
          body: JSON.stringify({ category, content }),
        });
        if (!this.token) return;
        this.shiftNotes = [created, ...this.shiftNotes];
        this.shiftNoteForm.text = '';
      }, 'Shift note saved.');
    },

    async toggleShiftNoteDone(note) {
      if (!note) return;
      try {
        const updated = await this.api(`/reports/shift-notes/${note.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ is_done: !note.is_done }),
        });
        if (!this.token) return;
        this.shiftNotes = this.shiftNotes.map(n => (n.id === note.id ? updated : n));
      } catch (err) {
        if (this.token) this.notify(err.message || 'Could not update shift note.', 'error');
      }
    },

    async deleteShiftNote(id) {
      try {
        await this.api(`/reports/shift-notes/${id}`, { method: 'DELETE' });
        if (!this.token) return;
        this.shiftNotes = this.shiftNotes.filter(n => n.id !== id);
        this.notify('Shift note removed.');
      } catch (err) {
        if (this.token) this.notify(err.message || 'Could not delete shift note.', 'error');
      }
    },

    selectTab(tab) {
      this.activeTab = tab;
      this.sidebarOpen = false;
      if (tab === 'menu') this.ensureSelectedProduct();
    },

    closeAllOverlays() {
      this.sidebarOpen = false;
      this.closeProfileSettings();
      this.voidModalSale = null;
      this.productModalOpen = false;
      this.categoryModalOpen = false;
      this.restockMaterial = null;
      this.materialModalOpen = false;
      this.stockActionMaterial = null;
      this.ledgerMaterial = null;
      this.unitModalOpen = false;
      this.poModalOpen = false;
      this.supplierModalOpen = false;
      this.inspectedPurchase = null;
      this.staffModalOpen = false;
      this.receiptModal = null;
      this.inspectedSaleId = null;
    },

    pageTitle() {
      return {
        overview: 'Overview',
        sales: 'Sales & Void History',
        menu: 'Menu & Recipes',
        roastery: 'Roastery & Beans',
        purchasing: 'Purchasing & Suppliers',
        analytics: 'Reports & Analytics',
        users: 'Staff Users',
      }[this.activeTab] || 'Overview';
    },

    liveQueueCount() {
      return this.liveQueueOrders().length;
    },

    async loadDashboardBackgroundTabs() {
      await Promise.allSettled([this.loadSalesHistory(), this.loadCatalogData()]);
      if (!this.token) return;
      const tail = [this.loadRoasteryData(), this.loadPurchases()];
      if (this.isAdmin()) tail.push(this.loadUsers());
      await Promise.allSettled(tail);
    },

    async loadDashboardAll() {
      this.busy = true;
      try {
        await this.loadOverview();
        if (!this.token) return;
        await this.loadDashboardBackgroundTabs();
      } catch (err) {
        if (this.token) this.notify(err.message || 'Could not refresh dashboard data.', 'error');
      } finally {
        this.busy = false;
      }
    },

    async loadOverview() {
      const today = this.localDateStr(0);
      const tz = this.tzOffsetParam();
      const [dash, rev, top, cogs, todayOrders, notes] = await Promise.all([
        this.api(`/reports/dashboard?${tz}`),
        this.api(`/reports/revenue?date_from=${encodeURIComponent(this.revFrom)}&date_to=${encodeURIComponent(this.revTo)}&${tz}`),
        this.api(`/reports/top-products?date_from=${encodeURIComponent(this.revFrom)}&date_to=${encodeURIComponent(this.revTo)}&${tz}`),
        this.api('/reports/cogs'),
        this.api(`/sales?date_from=${encodeURIComponent(today)}&date_to=${encodeURIComponent(today)}&${tz}&include_items=true`),
        this.api('/reports/shift-notes'),
      ]);
      if (!this.token) return;
      this.dashboard = dash || {};
      this.revenueRows = Array.isArray(rev) ? rev : [];
      this.topProducts = Array.isArray(top) ? top : [];
      this.analyticsTopProducts = this.topProducts;
      this.cogsRows = Array.isArray(cogs) ? cogs : [];
      this.todaySales = Array.isArray(todayOrders) ? todayOrders : [];
      this.shiftNotes = Array.isArray(notes) ? notes : [];
      this.queueStageMap = this._readJsonStore(SHIKA_BAR_STAGES_KEY);
      if (this.chartRange === 'today') {
        this.chartSales = this.todaySales;
      } else {
        await this.loadChartRangeData(this.chartRange);
      }
    },

    async setChartRange(range) {
      if (this.chartRange === range) return;
      this.chartRange = range;
      this.hoveredBarIdx = null;
      await this.loadChartRangeData(range);
    },

    async loadChartRangeData(range) {
      const today = this.localDateStr(0);
      if (range === 'today') {
        this.chartSales = this.todaySales;
        return;
      }
      const offset = range === '7d' ? -6 : -29;
      const from = this.localDateStr(offset);
      const rows = await this.api(`/sales?date_from=${encodeURIComponent(from)}&date_to=${encodeURIComponent(today)}&${this.tzOffsetParam()}&status=completed&include_items=true`);
      if (this.token) this.chartSales = Array.isArray(rows) ? rows : [];
    },

    _niceChartMax(rawMax, metric) {
      const val = Number(rawMax || 0);
      if (val <= 0) return metric === 'revenue' ? 100000 : 12;
      const stepTarget = val / 4;
      const mag = Math.pow(10, Math.floor(Math.log10(stepTarget)));
      const norm = stepTarget / mag;
      let niceStep;
      if (norm <= 1) niceStep = 1 * mag;
      else if (norm <= 1.5) niceStep = 1.5 * mag;
      else if (norm <= 2) niceStep = 2 * mag;
      else if (norm <= 2.5) niceStep = 2.5 * mag;
      else if (norm <= 5) niceStep = 5 * mag;
      else niceStep = 10 * mag;
      if (metric === 'cups') niceStep = Math.max(1, Math.ceil(niceStep));
      return niceStep * 4;
    },

    _chartRawBuckets() {
      const completed = (Array.isArray(this.chartSales) ? this.chartSales : []).filter(s => s.status !== 'cancelled');
      const buckets = [];
      if (this.chartRange === 'today') {
        const saleHours = completed
          .map(s => new Date(s.transaction_date).getHours())
          .filter(h => Number.isInteger(h) && h >= 0 && h <= 23);
        const startHour = saleHours.length > 0 ? Math.min(8, ...saleHours) : 8;
        const endHour = saleHours.length > 0 ? Math.max(19, ...saleHours) : 19;
        for (let h = startHour; h <= endHour; h += 1) {
          buckets.push({ key: `h-${h}`, label: `${String(h).padStart(2, '0')}:00`, hour: h, revenue: 0, cups: 0 });
        }
        for (const s of completed) {
          const h = new Date(s.transaction_date).getHours();
          const b = buckets.find(x => x.hour === h);
          if (b) {
            b.revenue += Number(s.total_amount || 0);
            b.cups += (s.items || []).reduce((sum, it) => sum + Number(it.quantity || 0), 0);
          }
        }
      } else if (this.chartRange === '7d') {
        for (let i = -6; i <= 0; i += 1) {
          const ds = this.localDateStr(i);
          const d = new Date(`${ds}T00:00:00`);
          buckets.push({
            key: ds,
            label: d.toLocaleDateString('en-US', { weekday: 'short' }),
            dateStr: ds,
            revenue: 0,
            cups: 0,
          });
        }
        for (const s of completed) {
          const d = new Date(s.transaction_date);
          const ds = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
          const b = buckets.find(x => x.dateStr === ds);
          if (b) {
            b.revenue += Number(s.total_amount || 0);
            b.cups += (s.items || []).reduce((sum, it) => sum + Number(it.quantity || 0), 0);
          }
        }
      } else {
        for (let idx = 0; idx < 6; idx += 1) {
          const startOff = -29 + idx * 5;
          const endOff = Math.min(0, startOff + 4);
          const startStr = this.localDateStr(startOff);
          const endStr = this.localDateStr(endOff);
          const sd = new Date(`${startStr}T00:00:00`);
          buckets.push({
            key: `${startStr}_${endStr}`,
            label: sd.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
            startStr,
            endStr,
            revenue: 0,
            cups: 0,
          });
        }
        for (const s of completed) {
          const d = new Date(s.transaction_date);
          const ds = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
          const b = buckets.find(x => ds >= x.startStr && ds <= x.endStr);
          if (b) {
            b.revenue += Number(s.total_amount || 0);
            b.cups += (s.items || []).reduce((sum, it) => sum + Number(it.quantity || 0), 0);
          }
        }
      }
      return buckets;
    },

    chartBars() {
      const buckets = this._chartRawBuckets();
      const rawMax = Math.max(0, ...buckets.map(b => (this.chartMetric === 'revenue' ? b.revenue : b.cups)));
      const scaleMax = this._niceChartMax(rawMax, this.chartMetric);
      return buckets.map(b => {
        const val = this.chartMetric === 'revenue' ? b.revenue : b.cups;
        const pct = val > 0 ? Math.max(3, Math.min(100, Number(((val / scaleMax) * 100).toFixed(2)))) : 0;
        return { ...b, pct };
      });
    },

    chartSeriesTotal() {
      return this._chartRawBuckets().reduce((sum, b) => sum + (this.chartMetric === 'revenue' ? b.revenue : b.cups), 0);
    },

    chartYAxisTicks() {
      const buckets = this._chartRawBuckets();
      const rawMax = Math.max(0, ...buckets.map(b => (this.chartMetric === 'revenue' ? b.revenue : b.cups)));
      const maxVal = this._niceChartMax(rawMax, this.chartMetric);
      const fmt = (v) => {
        if (this.chartMetric === 'cups') return String(Math.round(v));
        if (v >= 1000000) return `${Number((v / 1000000).toFixed(v % 1000000 === 0 ? 0 : 1))}M`;
        if (v >= 1000) return `${Number((v / 1000).toFixed(v % 1000 === 0 ? 0 : 1))}k`;
        return String(Math.round(v));
      };
      return [fmt(maxVal), fmt(maxVal * 0.75), fmt(maxVal * 0.5), fmt(maxVal * 0.25), '0'];
    },

    activeChartBarIdx() {
      if (this.hoveredBarIdx !== null) return this.hoveredBarIdx;
      const bars = this.chartBars();
      let bestIdx = -1;
      let bestVal = 0;
      bars.forEach((b, i) => {
        const v = this.chartMetric === 'revenue' ? b.revenue : b.cups;
        if (v >= bestVal && v > 0) {
          bestVal = v;
          bestIdx = i;
        }
      });
      return bestIdx;
    },

    hoveredChartBar() {
      if (this.hoveredBarIdx === null) return null;
      return this.chartBars()[this.hoveredBarIdx] || null;
    },

    avgTicketToday() {
      const tx = Number(this.dashboard?.today_transactions || 0);
      if (tx <= 0) return 0;
      return Number(this.dashboard?.today_revenue || 0) / tx;
    },

    // Live Bar Queue helpers shared with /pos/orders stage map
    orderStage(order) {
      return shikaResolveOrderStage(order, this.queueStageMap, this.localDateStr(0));
    },

    stageLabel(stageId) {
      return { queued: 'Queued', brewing: 'Brewing', ready: 'Ready', served: 'Served', cancelled: 'Cancelled' }[stageId] || 'Queued';
    },

    queueNextLabel(stageId) {
      return { queued: 'Start Brew', brewing: 'Mark Ready', ready: 'Complete' }[stageId] || '';
    },

    liveQueueOrders() {
      return (Array.isArray(this.todaySales) ? this.todaySales : [])
        .filter(o => o.status !== 'cancelled' && ['queued', 'brewing', 'ready'].includes(this.orderStage(o)))
        .sort((a, b) => new Date(a.transaction_date) - new Date(b.transaction_date));
    },

    advanceQueueOrder(order) {
      const cur = this.orderStage(order);
      const nextMap = { queued: 'brewing', brewing: 'ready', ready: 'served' };
      const next = nextMap[cur];
      if (!next) return;
      const dbStatus = SHIKA_STAGE_TO_DB[next];
      if (dbStatus) order.order_status = dbStatus;
      const updated = { ...this.queueStageMap, [order.id]: next };
      this.queueStageMap = updated;
      this._writeJsonStore(SHIKA_BAR_STAGES_KEY, updated);
      this.notify(`${this.shortInvoice(order.invoice_number)} moved to ${this.stageLabel(next)}.`);
      if (dbStatus && order.status !== 'cancelled') {
        this.api(`/sales/${order.id}/order-status`, {
          method: 'PATCH',
          body: JSON.stringify({ order_status: dbStatus }),
        }).catch(() => {});
      }
    },

    ticketChannel(order) {
      if (!order) return '';
      if (order.order_type === 'take_away') return 'Takeaway';
      const m = String(order.customer_name || '').match(/\(([^)]+)\)\s*$/);
      return m ? m[1].trim() : 'Counter';
    },

    ticketGuest(order) {
      if (!order) return '';
      const clean = String(order.customer_name || '').replace(/\s*\([^)]+\)\s*$/, '').trim();
      return clean || 'Guest';
    },

    shortInvoice(inv) {
      return String(inv || '').replace(/^INV-\d{8}-/, '#');
    },

    formatCountdown(seconds) {
      const secs = Math.max(0, Math.ceil(Number(seconds || 0)));
      const mins = Math.floor(secs / 60);
      const rem = secs % 60;
      return `${String(mins).padStart(2, '0')}:${String(rem).padStart(2, '0')}`;
    },

    itemSummaryLine(order) {
      return (order?.items || []).map(it => `${it.quantity}× ${it.product_name}`).join(', ');
    },

    itemCategoryName(it) {
      return it?.category_name || this.productById[it?.product_id]?.category_name || 'Menu Item';
    },

    paymentLabel(method) {
      return { qris: 'QRIS / QR', cash: 'Cash', debit: 'Debit / Card' }[String(method || '').toLowerCase()] || String(method || '').toUpperCase();
    },

    hasRecipe(row) {
      return Boolean(row?.has_recipe) && Number(row?.estimated_cogs || 0) > 0;
    },

    // Sales & Voids
    async loadSalesHistory() {
      const rows = await this.api('/sales?include_items=true');
      if (this.token) this.sales = Array.isArray(rows) ? rows : [];
    },

    netCompletedSales() {
      return this.sales.filter(s => s.status !== 'cancelled').reduce((sum, s) => sum + Number(s.total_amount || 0), 0);
    },

    voidedValueTotal() {
      return this.sales.filter(s => s.status === 'cancelled').reduce((sum, s) => sum + Number(s.total_amount || 0), 0);
    },

    grossBeforeVoids() {
      return this.netCompletedSales() + this.voidedValueTotal();
    },

    completedTicketsCount() {
      return this.sales.filter(s => s.status !== 'cancelled').length;
    },

    voidedTicketsCount() {
      return this.sales.filter(s => s.status === 'cancelled').length;
    },

    voidRatePct() {
      if (this.sales.length === 0) return '0.0';
      return ((this.voidedTicketsCount() / this.sales.length) * 100).toFixed(1);
    },

    tenderSummary() {
      const acc = {
        qris: { amount: 0, count: 0 },
        cash: { amount: 0, count: 0 },
        debit: { amount: 0, count: 0 },
      };
      for (const s of this.sales) {
        if (s.status === 'cancelled') continue;
        const m = String(s.payment_method || '').toLowerCase();
        if (acc[m]) {
          acc[m].amount += Number(s.total_amount || 0);
          acc[m].count += 1;
        }
      }
      return acc;
    },

    saleVoidReason(saleId) {
      return this.voidReasonMap[saleId] || 'Voided by manager';
    },

    filteredSales() {
      const q = this.salesSearch.trim().toLowerCase();
      return this.sales.filter(s => {
        if (this.salesStatusTab === 'completed' && s.status === 'cancelled') return false;
        if (this.salesStatusTab === 'cancelled' && s.status !== 'cancelled') return false;
        if (this.salesTenderFilter && String(s.payment_method || '').toLowerCase() !== this.salesTenderFilter) return false;
        if (!q) return true;
        const hay = `${s.invoice_number || ''} ${this.shortInvoice(s.invoice_number)} ${s.customer_name || ''} ${this.itemSummaryLine(s)} ${this.saleVoidReason(s.id)}`.toLowerCase();
        return hay.includes(q);
      });
    },

    inspectSale(sale) {
      this.inspectedSaleId = this.inspectedSaleId === sale.id ? null : sale.id;
    },

    closeInspect() {
      this.inspectedSaleId = null;
    },

    openVoidModal(sale) {
      this.voidModalSale = sale;
      this.voidReason = '';
    },

    closeVoidModal() {
      this.voidModalSale = null;
      this.voidReason = '';
    },

    async confirmVoidSale() {
      if (!this.voidModalSale) return;
      const target = this.voidModalSale;
      const reason = this.voidReason.trim() || 'Voided by manager';
      await this._runAction('busy', async () => {
        await this.api(`/sales/${target.id}/cancel`, { method: 'POST' });
        const nextReasons = { ...this.voidReasonMap, [target.id]: reason };
        this.voidReasonMap = nextReasons;
        this._writeJsonStore(VOID_REASONS_KEY, nextReasons);
        this.closeVoidModal();
        await Promise.all([this.loadSalesHistory(), this.loadOverview(), this.loadRoasteryData()]);
      }, `Ticket ${this.shortInvoice(target.invoice_number)} voided and stock restored.`);
    },

    async openReceipt(saleId) {
      await this._runAction('busy', async () => {
        this.receiptModal = await this.api(`/sales/${saleId}/receipt`);
      });
    },

    // Menu & Recipes
    async loadCatalogData() {
      const [cats, prods, rms] = await Promise.all([
        this.api('/categories'),
        this.api('/products?active_only=false'),
        this.api('/raw-materials'),
      ]);
      if (!this.token) return;
      this.categories = Array.isArray(cats) ? cats : [];
      this.products = Array.isArray(prods) ? prods : [];
      this.rawMaterials = Array.isArray(rms) ? rms : [];
      const map = {};
      for (const p of this.products) {
        map[p.id] = { category_id: p.category_id, category_name: p.category_name || 'Menu Item' };
      }
      this.productById = map;
      await this.ensureSelectedProduct();
    },

    categoryProductCount(catId) {
      return this.products.filter(p => Number(p.category_id) === Number(catId)).length;
    },

    get filteredProducts() {
      const q = this.productSearch.trim().toLowerCase();
      return this.products.filter(p => {
        if (this.productCategoryFilter && String(p.category_id) !== this.productCategoryFilter) return false;
        if (!q) return true;
        return `${p.name || ''} ${p.sku || ''} ${p.category_name || ''}`.toLowerCase().includes(q);
      });
    },

    async ensureSelectedProduct() {
      const list = this.filteredProducts;
      if (list.length === 0) {
        this.selectedProductId = null;
        this.recipeProduct = null;
        this.recipeItems = [];
        return;
      }
      if (!list.some(p => p.id === this.selectedProductId)) {
        await this.selectProduct(list[0]);
      }
    },

    async selectProduct(p) {
      if (!p) return;
      this.selectedProductId = p.id;
      this.recipeProduct = p;
      this.recipeAddForm = { raw_material_id: '', quantity_required: '' };
      this.methodStepsDraft = this.selectedMethodSteps().join('\n');
      try {
        const items = await this.api(`/products/${p.id}/recipes`);
        if (this.token && this.selectedProductId === p.id) {
          this.recipeItems = Array.isArray(items) ? items : [];
        }
      } catch {
        this.recipeItems = [];
      }
    },

    selectedProductCogs() {
      if (!this.selectedProduct) return null;
      return this.cogsRows.find(r => r.product_id === this.selectedProduct.id) || null;
    },

    selectedMethodSteps() {
      if (!this.selectedProductId) return [];
      const arr = this.recipeStepsMap[this.selectedProductId];
      return Array.isArray(arr) ? arr : [];
    },

    saveMethodSteps() {
      if (!this.selectedProductId) return;
      const steps = this.methodStepsDraft.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
      const next = { ...this.recipeStepsMap, [this.selectedProductId]: steps };
      this.recipeStepsMap = next;
      this._writeJsonStore(RECIPE_STEPS_KEY, next);
      this.notify('Preparation steps saved.');
    },

    openNewProductModal() {
      this.productForm = { id: null, category_id: this.categories[0] ? String(this.categories[0].id) : '', sku: '', name: '', price: '', image_url: '' };
      this.productModalOpen = true;
    },

    openEditProductModal(p) {
      this.productForm = {
        id: p.id,
        category_id: String(p.category_id),
        sku: p.sku,
        name: p.name,
        price: String(p.price),
        image_url: p.image_url || '',
      };
      this.productModalOpen = true;
    },

    async uploadProductImage(event) {
      const file = event?.target?.files?.[0];
      if (event?.target) event.target.value = '';
      if (!file) return;
      this.productImageUploading = true;
      try {
        const imageData = await this._readLocalImageFile(file);
        const res = await this.api('/products/upload-image', {
          method: 'POST',
          body: JSON.stringify({ image_data: imageData }),
        });
        if (!this.token) return;
        this.productForm.image_url = res?.image_url || '';
        this.notify('Item photo uploaded.');
      } catch (err) {
        if (this.token) this.notify(err.message || 'Could not upload item photo.', 'error');
      } finally {
        this.productImageUploading = false;
      }
    },

    removeProductImage() {
      this.productForm.image_url = '';
    },

    async saveProduct() {
      const f = this.productForm;
      if (!f.category_id || !f.sku.trim() || !f.name.trim() || f.price === '') {
        this.notify('Category, SKU, name, and price are required.', 'error');
        return;
      }
      const payload = {
        category_id: Number(f.category_id),
        sku: f.sku.trim(),
        name: f.name.trim(),
        price: Number(f.price).toFixed(2),
        image_url: f.image_url.trim() || null,
      };
      await this._runAction('busy', async () => {
        const saved = await this.api(f.id ? `/products/${f.id}` : '/products', {
          method: f.id ? 'PATCH' : 'POST',
          body: JSON.stringify(payload),
        });
        this.productModalOpen = false;
        await Promise.all([this.loadCatalogData(), this.loadOverview()]);
        if (saved?.id) {
          const found = this.products.find(x => x.id === saved.id);
          if (found) await this.selectProduct(found);
        }
      }, f.id ? 'Item updated.' : 'Item created.');
    },

    async toggleProductActive(p) {
      await this._runAction('busy', async () => {
        if (p.is_active) {
          await this.api(`/products/${p.id}`, { method: 'DELETE' });
        } else {
          await this.api(`/products/${p.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: true }) });
        }
        await Promise.all([this.loadCatalogData(), this.loadOverview()]);
      }, p.is_active ? 'Item hidden from POS.' : 'Item available on POS.');
    },

    editCategory(c) {
      this.catForm = { id: c.id, name: c.name, description: c.description || '' };
    },

    resetCategoryForm() {
      this.catForm = { id: null, name: '', description: '' };
    },

    async saveCategory() {
      const c = this.catForm;
      if (!c.name.trim()) {
        this.notify('Category name is required.', 'error');
        return;
      }
      await this._runAction('busy', async () => {
        await this.api(c.id ? `/categories/${c.id}` : '/categories', {
          method: c.id ? 'PATCH' : 'POST',
          body: JSON.stringify({ name: c.name.trim(), description: c.description.trim() || null }),
        });
        this.resetCategoryForm();
        await this.loadCatalogData();
      }, c.id ? 'Category updated.' : 'Category created.');
    },

    async deleteCategory(id) {
      await this._runAction('busy', async () => {
        await this.api(`/categories/${id}`, { method: 'DELETE' });
        await this.loadCatalogData();
      }, 'Category deleted.');
    },

    async addRecipeItem() {
      if (!this.selectedProduct) return;
      const f = this.recipeAddForm;
      if (!f.raw_material_id || !(Number(f.quantity_required) > 0)) {
        this.notify('Choose a raw material and positive quantity.', 'error');
        return;
      }
      await this._runAction('busy', async () => {
        await this.api(`/products/${this.selectedProduct.id}/recipes`, {
          method: 'POST',
          body: JSON.stringify({
            raw_material_id: Number(f.raw_material_id),
            quantity_required: Number(f.quantity_required).toFixed(2),
          }),
        });
        this.recipeAddForm = { raw_material_id: '', quantity_required: '' };
        this.recipeItems = await this.api(`/products/${this.selectedProduct.id}/recipes`);
        this.cogsRows = await this.api('/reports/cogs');
      }, 'Ingredient added to recipe.');
    },

    async updateRecipeQty(item) {
      if (!this.selectedProduct || !(Number(item.quantity_required) > 0)) return;
      await this._runAction('busy', async () => {
        await this.api(`/products/${this.selectedProduct.id}/recipes/${item.raw_material_id}`, {
          method: 'PUT',
          body: JSON.stringify({ quantity_required: Number(item.quantity_required).toFixed(2) }),
        });
        this.recipeItems = await this.api(`/products/${this.selectedProduct.id}/recipes`);
        this.cogsRows = await this.api('/reports/cogs');
      }, 'Recipe quantity updated.');
    },

    async deleteRecipeItem(rawMaterialId) {
      if (!this.selectedProduct) return;
      await this._runAction('busy', async () => {
        await this.api(`/products/${this.selectedProduct.id}/recipes/${rawMaterialId}`, { method: 'DELETE' });
        this.recipeItems = await this.api(`/products/${this.selectedProduct.id}/recipes`);
        this.cogsRows = await this.api('/reports/cogs');
      }, 'Ingredient removed from recipe.');
    },

    // Roastery & Beans
    async loadRoasteryData() {
      const [inv, low, sups, units] = await Promise.all([
        this.api('/inventory'),
        this.api('/inventory/low-stock'),
        this.api('/suppliers'),
        this.api('/units'),
      ]);
      if (!this.token) return;
      this.inventoryRows = Array.isArray(inv) ? inv : [];
      this.lowStockRows = Array.isArray(low) ? low : [];
      this.lowStockItems = this.lowStockRows;
      this.suppliers = Array.isArray(sups) ? sups : [];
      this.units = Array.isArray(units) ? units : [];
    },

    roasteryTotalWeightLabel() {
      const gramItems = this.inventoryRows.filter(r => ['gr', 'g'].includes(String(r.unit_symbol || '').toLowerCase()));
      if (gramItems.length === 0) return `${this.inventoryRows.length} lots`;
      const totalGrams = gramItems.reduce((sum, r) => sum + Number(r.current_stock || 0), 0);
      return `${(totalGrams / 1000).toFixed(1)} kg`;
    },

    formatStockQty(val, symbol) {
      const n = Number(val || 0);
      const sym = String(symbol || '').toLowerCase();
      if (sym === 'gr' || sym === 'g') return `${(n / 1000).toFixed(2)} kg`;
      if (sym === 'ml') return `${(n / 1000).toFixed(2)} L`;
      return `${n} ${symbol || ''}`.trim();
    },

    distributionRows() {
      const src = this.inventoryRows;
      if (src.length === 0) return [];
      let items = [];
      if (this.roasteryGroupMode === 'unit') {
        const grouped = {};
        for (const r of src) {
          const sym = String(r.unit_symbol || 'unit');
          if (!grouped[sym]) grouped[sym] = { key: `u-${sym}`, label: `Unit: ${sym}`, qty: 0, par: 0, symbol: sym };
          grouped[sym].qty += Number(r.current_stock || 0);
          grouped[sym].par += Number(r.minimum_stock || 0);
        }
        items = Object.values(grouped).sort((a, b) => b.qty - a.qty);
      } else {
        const dry = src.filter(r => ['gr', 'g'].includes(String(r.unit_symbol || '').toLowerCase()));
        const base = dry.length > 0 ? dry : src;
        items = [...base]
          .sort((a, b) => Number(b.current_stock || 0) - Number(a.current_stock || 0))
          .slice(0, 8)
          .map(r => ({
            key: `m-${r.id}`,
            label: r.name,
            qty: Number(r.current_stock || 0),
            par: Number(r.minimum_stock || 0),
            symbol: r.unit_symbol,
          }));
      }

      const totalQty = items.reduce((sum, x) => sum + x.qty, 0);
      const maxScale = Math.max(1, ...items.map(x => Math.max(x.qty, x.par)));
      const circ = 2 * Math.PI * 46;
      let accOffset = 0;

      return items.map(it => {
        const share = totalQty > 0 ? (it.qty / totalQty) * 100 : 0;
        const segLen = totalQty > 0 ? (it.qty / totalQty) * circ : 0;
        const dash = Math.max(0, segLen - 2);
        const offset = -accOffset;
        accOffset += segLen;
        return {
          ...it,
          sharePct: share.toFixed(1),
          barPct: Math.max(3, Math.round((it.qty / maxScale) * 100)),
          parPct: Math.min(98, Math.max(2, Math.round((it.par / maxScale) * 100))),
          belowPar: it.qty <= it.par,
          displayQty: this.formatStockQty(it.qty, it.symbol),
          displayPar: this.formatStockQty(it.par, it.symbol),
          dash: dash.toFixed(2),
          gap: circ.toFixed(2),
          offset: offset.toFixed(2),
        };
      });
    },

    hoveredDistRow() {
      const rows = this.distributionRows();
      if (rows.length === 0) return null;
      return rows.find(r => r.key === this.roasteryHoveredKey) || rows[0];
    },

    roasteryDonutSvg() {
      const rows = this.distributionRows();
      const activeKey = this.hoveredDistRow()?.key || '';
      const segs = rows.map((seg) => {
        const isActive = seg.key === activeKey;
        const stroke = isActive ? 'var(--chart-active)' : 'var(--chart-muted)';
        const width = isActive ? 16 : 13;
        return `<circle cx="60" cy="60" r="46" fill="none" stroke="${stroke}" stroke-width="${width}" stroke-dasharray="${seg.dash} ${seg.gap}" stroke-dashoffset="${seg.offset}"></circle>`;
      }).join('');
      return `<svg class="adm-donut-svg" viewBox="0 0 120 120" aria-hidden="true"><circle cx="60" cy="60" r="46" fill="none" stroke="var(--surface-subtle)" stroke-width="13"></circle>${segs}</svg>`;
    },

    filteredRoasteryRows() {
      const q = this.roasterySearch.trim().toLowerCase();
      if (!q) return this.inventoryRows;
      return this.inventoryRows.filter(r => `${r.name || ''} ${r.sku || ''} ${r.unit_symbol || ''}`.toLowerCase().includes(q));
    },

    openNewMaterialModal() {
      this.materialForm = {
        id: null,
        unit_id: this.units[0] ? String(this.units[0].id) : '',
        sku: '',
        name: '',
        minimum_stock: '10',
        image_url: '',
      };
      this.materialModalOpen = true;
    },

    openEditMaterialModal(rm) {
      this.materialForm = {
        id: rm.id,
        unit_id: String(rm.unit_id),
        sku: rm.sku || '',
        name: rm.name || '',
        minimum_stock: String(rm.minimum_stock ?? '0'),
        image_url: rm.image_url || '',
      };
      this.materialModalOpen = true;
    },

    async uploadMaterialImage(event) {
      const file = event?.target?.files?.[0];
      if (event?.target) event.target.value = '';
      if (!file) return;
      this.materialImageUploading = true;
      try {
        const imageData = await this._readLocalImageFile(file);
        const res = await this.api('/raw-materials/upload-image', {
          method: 'POST',
          body: JSON.stringify({ image_data: imageData }),
        });
        if (!this.token) return;
        this.materialForm.image_url = res?.image_url || '';
        this.notify('Lot photo uploaded.');
      } catch (err) {
        if (this.token) this.notify(err.message || 'Could not upload lot photo.', 'error');
      } finally {
        this.materialImageUploading = false;
      }
    },

    removeMaterialImage() {
      this.materialForm.image_url = '';
    },

    async saveMaterial() {
      const f = this.materialForm;
      if (!f.unit_id || !f.sku.trim() || !f.name.trim() || f.minimum_stock === '') {
        this.notify('Name, SKU, unit, and par threshold are required.', 'error');
        return;
      }
      const payload = {
        unit_id: Number(f.unit_id),
        sku: f.sku.trim(),
        name: f.name.trim(),
        minimum_stock: Number(f.minimum_stock).toFixed(2),
        image_url: f.image_url.trim() || null,
      };
      await this._runAction('busy', async () => {
        await this.api(f.id ? `/raw-materials/${f.id}` : '/raw-materials', {
          method: f.id ? 'PATCH' : 'POST',
          body: JSON.stringify(payload),
        });
        this.materialModalOpen = false;
        await Promise.all([this.loadRoasteryData(), this.loadCatalogData(), this.loadOverview()]);
      }, f.id ? 'Roastery lot updated.' : 'Roastery lot created.');
    },

    openRestockModal(rm) {
      this.restockMaterial = rm;
      this.restockForm = {
        supplier_id: this.suppliers[0] ? String(this.suppliers[0].id) : '',
        quantity: String(Math.max(1, Number(rm.minimum_stock || 10))),
        unit_price: String(rm.latest_purchase_price || 0),
        notes: `Restock ${rm.sku}`,
      };
    },

    async submitQuickRestock() {
      if (!this.restockMaterial || !this.restockForm.supplier_id) {
        this.notify('Select a supplier and valid quantity.', 'error');
        return;
      }
      await this._runAction('busy', async () => {
        await this.api('/purchases', {
          method: 'POST',
          body: JSON.stringify({
            supplier_id: Number(this.restockForm.supplier_id),
            notes: this.restockForm.notes.trim() || null,
            items: [{
              raw_material_id: this.restockMaterial.id,
              quantity: Number(this.restockForm.quantity).toFixed(2),
              unit_price: Number(this.restockForm.unit_price || 0).toFixed(2),
            }],
          }),
        });
        this.restockMaterial = null;
        await Promise.all([this.loadRoasteryData(), this.loadPurchases(), this.loadOverview()]);
      }, 'Purchase order recorded and stock updated.');
    },

    // Inventory Control: Opname, Waste, Mutation Ledger, Units
    openStockActionModal(rm, mode = 'adjust') {
      this.stockActionMaterial = rm;
      this.stockActionMode = mode;
      this.adjustForm = { actual_stock: String(rm.current_stock ?? 0), notes: '' };
      this.wasteForm = { quantity: '', notes: '' };
    },

    stockVarianceLabel() {
      if (!this.stockActionMaterial || this.adjustForm.actual_stock === '') return '0';
      const cur = Number(this.stockActionMaterial.current_stock || 0);
      const actual = Number(this.adjustForm.actual_stock);
      if (!Number.isFinite(actual)) return '-';
      const diff = Number((actual - cur).toFixed(2));
      const sym = this.stockActionMaterial.unit_symbol || '';
      if (diff === 0) return 'No change';
      return `${diff > 0 ? '+' : ''}${diff} ${sym}`.trim();
    },

    async submitStockAdjustment() {
      if (!this.stockActionMaterial) return;
      const notes = String(this.adjustForm.notes || '').trim();
      if (!notes) {
        this.notify('Please enter an opname audit note.', 'error');
        return;
      }
      await this._runAction('busy', async () => {
        await this.api('/inventory/adjustment', {
          method: 'POST',
          body: JSON.stringify({
            raw_material_id: this.stockActionMaterial.id,
            actual_stock: Number(this.adjustForm.actual_stock).toFixed(2),
            notes,
          }),
        });
        this.stockActionMaterial = null;
        await Promise.all([this.loadRoasteryData(), this.loadOverview()]);
      }, 'Stock opname adjustment recorded.');
    },

    async submitStockWaste() {
      if (!this.stockActionMaterial) return;
      const qty = Number(this.wasteForm.quantity);
      const notes = String(this.wasteForm.notes || '').trim();
      if (!(qty > 0) || !notes) {
        this.notify('Enter a positive waste quantity and reason.', 'error');
        return;
      }
      await this._runAction('busy', async () => {
        await this.api('/inventory/waste', {
          method: 'POST',
          body: JSON.stringify({
            raw_material_id: this.stockActionMaterial.id,
            quantity: qty.toFixed(2),
            notes,
          }),
        });
        this.stockActionMaterial = null;
        await Promise.all([this.loadRoasteryData(), this.loadOverview()]);
      }, 'Waste entry recorded and stock updated.');
    },

    async openMutationLedger(rm) {
      this.ledgerMaterial = rm;
      this.ledgerMutations = [];
      try {
        const rows = await this.api(`/inventory/${rm.id}/mutations`);
        if (this.token && this.ledgerMaterial?.id === rm.id) {
          this.ledgerMutations = Array.isArray(rows) ? rows : [];
        }
      } catch (err) {
        if (this.token) this.notify(err.message || 'Could not load stock ledger.', 'error');
      }
    },

    async saveUnit() {
      const f = this.unitForm;
      if (!f.name.trim() || !f.symbol.trim()) {
        this.notify('Unit name and symbol are required.', 'error');
        return;
      }
      await this._runAction('busy', async () => {
        await this.api(f.id ? `/units/${f.id}` : '/units', {
          method: f.id ? 'PATCH' : 'POST',
          body: JSON.stringify({ name: f.name.trim(), symbol: f.symbol.trim() }),
        });
        this.unitForm = { id: null, name: '', symbol: '' };
        await this.loadRoasteryData();
      }, f.id ? 'Unit updated.' : 'Unit added.');
    },

    async deleteUnit(unitId) {
      await this._runAction('busy', async () => {
        await this.api(`/units/${unitId}`, { method: 'DELETE' });
        await this.loadRoasteryData();
      }, 'Unit removed.');
    },

    // Purchasing & Suppliers
    async loadPurchases() {
      const [rows, summary] = await Promise.all([
        this.api('/purchases'),
        this.api('/purchases/summary'),
      ]);
      if (!this.token) return;
      this.purchases = Array.isArray(rows) ? rows : [];
      this.purchaseSummary = summary || {
        total_orders: this.purchases.length,
        total_spend: this.totalProcurementSpend(),
        active_suppliers: this.suppliers.length,
      };
    },

    totalProcurementSpend() {
      return this.purchases.reduce((sum, po) => sum + Number(po.total_cost || 0), 0);
    },

    filteredPurchases() {
      const q = this.purchasingSearch.trim().toLowerCase();
      if (!q) return this.purchases;
      return this.purchases.filter(po =>
        `${po.po_number || ''} ${po.supplier_name || ''} ${po.created_by || ''} ${po.notes || ''}`.toLowerCase().includes(q)
      );
    },

    filteredSuppliers() {
      const q = this.purchasingSearch.trim().toLowerCase();
      if (!q) return this.suppliers;
      return this.suppliers.filter(s =>
        `${s.name || ''} ${s.phone || ''} ${s.email || ''} ${s.address || ''}`.toLowerCase().includes(q)
      );
    },

    async inspectPurchase(poId) {
      if (this.inspectedPurchase?.id === poId) {
        this.inspectedPurchase = null;
        return;
      }
      try {
        const detail = await this.api(`/purchases/${poId}`);
        if (this.token) this.inspectedPurchase = detail;
      } catch (err) {
        if (this.token) this.notify(err.message || 'Could not load purchase order details.', 'error');
      }
    },

    openNewPurchaseModal() {
      this.poForm = {
        supplier_id: this.suppliers[0] ? String(this.suppliers[0].id) : '',
        notes: '',
        items: [{ raw_material_id: '', quantity: '', unit_price: '' }],
      };
      this.poModalOpen = true;
    },

    addPoLine() {
      this.poForm.items.push({ raw_material_id: '', quantity: '', unit_price: '' });
    },

    removePoLine(idx) {
      if (this.poForm.items.length <= 1) return;
      this.poForm.items.splice(idx, 1);
    },

    prefillPoLinePrice(line) {
      const rm = this.inventoryRows.find(r => String(r.id) === String(line.raw_material_id));
      if (rm && (line.unit_price === '' || Number(line.unit_price) === 0)) {
        line.unit_price = String(rm.latest_purchase_price || 0);
      }
    },

    poFormTotal() {
      return (this.poForm.items || []).reduce(
        (sum, it) => sum + Number(it.quantity || 0) * Number(it.unit_price || 0),
        0,
      );
    },

    async submitPurchaseOrder() {
      const f = this.poForm;
      if (!f.supplier_id) {
        this.notify('Please select a supplier.', 'error');
        return;
      }
      const validItems = (f.items || []).filter(it => it.raw_material_id && Number(it.quantity) > 0);
      if (validItems.length === 0) {
        this.notify('Add at least one raw material with a positive quantity.', 'error');
        return;
      }
      await this._runAction('busy', async () => {
        const created = await this.api('/purchases', {
          method: 'POST',
          body: JSON.stringify({
            supplier_id: Number(f.supplier_id),
            notes: f.notes.trim() || null,
            items: validItems.map(it => ({
              raw_material_id: Number(it.raw_material_id),
              quantity: Number(it.quantity).toFixed(2),
              unit_price: Number(it.unit_price || 0).toFixed(2),
            })),
          }),
        });
        this.poModalOpen = false;
        await Promise.all([this.loadPurchases(), this.loadRoasteryData(), this.loadOverview()]);
        if (created?.id) await this.inspectPurchase(created.id);
      }, 'Purchase order recorded and stock updated.');
    },

    openNewSupplierModal() {
      this.supplierForm = { id: null, name: '', phone: '', email: '', address: '' };
      this.supplierModalOpen = true;
    },

    openEditSupplierModal(sup) {
      this.supplierForm = {
        id: sup.id,
        name: sup.name || '',
        phone: sup.phone || '',
        email: sup.email || '',
        address: sup.address || '',
      };
      this.supplierModalOpen = true;
    },

    async saveSupplier() {
      const f = this.supplierForm;
      if (!f.name.trim()) {
        this.notify('Supplier name is required.', 'error');
        return;
      }
      const payload = {
        name: f.name.trim(),
        phone: f.phone.trim() || null,
        email: f.email.trim() || null,
        address: f.address.trim() || null,
      };
      await this._runAction('busy', async () => {
        await this.api(f.id ? `/suppliers/${f.id}` : '/suppliers', {
          method: f.id ? 'PATCH' : 'POST',
          body: JSON.stringify(payload),
        });
        this.supplierModalOpen = false;
        await Promise.all([this.loadRoasteryData(), this.loadPurchases()]);
      }, f.id ? 'Supplier updated.' : 'Supplier added.');
    },

    async deleteSupplier(sup) {
      await this._runAction('busy', async () => {
        await this.api(`/suppliers/${sup.id}`, { method: 'DELETE' });
        await Promise.all([this.loadRoasteryData(), this.loadPurchases()]);
      }, `Supplier ${sup.name} removed.`);
    },

    // Reports & Analytics
    async applyAnalyticsPreset(preset) {
      this.analyticsPreset = preset;
      const offsetMap = { today: 0, '7d': -6, '30d': -29, '90d': -89 };
      const offset = offsetMap[preset] ?? -29;
      this.revFrom = this.localDateStr(offset);
      this.revTo = this.localDateStr(0);
      await this.loadAnalyticsReports();
    },

    async loadAnalyticsReports() {
      if (!this.revFrom || !this.revTo) return;
      const tz = this.tzOffsetParam();
      await this._runAction('busy', async () => {
        const [rev, top, cogs] = await Promise.all([
          this.api(`/reports/revenue?date_from=${encodeURIComponent(this.revFrom)}&date_to=${encodeURIComponent(this.revTo)}&${tz}`),
          this.api(`/reports/top-products?date_from=${encodeURIComponent(this.revFrom)}&date_to=${encodeURIComponent(this.revTo)}&${tz}`),
          this.api('/reports/cogs'),
        ]);
        if (!this.token) return;
        this.revenueRows = Array.isArray(rev) ? rev : [];
        this.analyticsTopProducts = Array.isArray(top) ? top : [];
        this.cogsRows = Array.isArray(cogs) ? cogs : [];
      });
    },

    analyticsTotals() {
      return (Array.isArray(this.revenueRows) ? this.revenueRows : []).reduce(
        (acc, r) => ({
          tickets: acc.tickets + Number(r.total_transactions || 0),
          gross: acc.gross + Number(r.gross_sales || 0),
          discounts: acc.discounts + Number(r.total_discounts || 0),
          tax: acc.tax + Number(r.total_tax || 0),
          net: acc.net + Number(r.net_revenue || 0),
        }),
        { tickets: 0, gross: 0, discounts: 0, tax: 0, net: 0 },
      );
    },

    revenueSharePct(netVal) {
      const total = this.analyticsTotals().net;
      if (total <= 0) return '0.0';
      return ((Number(netVal || 0) / total) * 100).toFixed(1);
    },

    costedMenuCount() {
      return this.cogsRows.filter(r => this.hasRecipe(r)).length;
    },

    averageMarginPct() {
      const costed = this.cogsRows.filter(r => this.hasRecipe(r));
      if (costed.length === 0) return '0.0';
      const avg = costed.reduce((sum, r) => sum + Number(r.margin_percentage || 0), 0) / costed.length;
      return avg.toFixed(1);
    },

    filteredMarginRows() {
      const q = this.analyticsMarginSearch.trim().toLowerCase();
      const rows = (Array.isArray(this.cogsRows) ? this.cogsRows : []).filter(r => {
        if (!q) return true;
        return `${r.product_name || ''} ${r.sku || ''}`.toLowerCase().includes(q);
      });
      const sort = this.analyticsMarginSort;
      return [...rows].sort((a, b) => {
        if (sort === 'margin_desc') return Number(b.margin_percentage || 0) - Number(a.margin_percentage || 0);
        if (sort === 'margin_asc') return Number(a.margin_percentage || 0) - Number(b.margin_percentage || 0);
        if (sort === 'cogs_desc') return Number(b.estimated_cogs || 0) - Number(a.estimated_cogs || 0);
        return Number(b.gross_profit || 0) - Number(a.gross_profit || 0);
      });
    },

    async exportAnalyticsCsv() {
      if (!this.revFrom || !this.revTo) return;
      try {
        const res = await fetch(
          `/reports/analytics/export?date_from=${encodeURIComponent(this.revFrom)}&date_to=${encodeURIComponent(this.revTo)}&${this.tzOffsetParam()}`,
          { headers: this.token ? { Authorization: `Bearer ${this.token}` } : {} },
        );
        if (res.status === 401) {
          this.logout();
          return;
        }
        if (!res.ok) throw new Error(`Export failed (${res.status})`);
        const csvText = await res.text();
        const blob = new Blob([csvText], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `shika-analytics-${this.revFrom}-to-${this.revTo}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        this.notify('Analytics CSV exported.');
      } catch (err) {
        if (this.token) this.notify(err.message || 'Could not export analytics CSV.', 'error');
      }
    },

    // Staff Users
    async loadUsers() {
      if (!this.isAdmin()) return;
      const rows = await this.api('/users');
      if (this.token) this.users = Array.isArray(rows) ? rows : [];
    },

    activeUsersCount() {
      return this.users.filter(u => u.is_active).length;
    },

    filteredStaff() {
      const q = this.staffSearch.trim().toLowerCase();
      return this.users.filter(u => {
        if (this.staffStatusTab === 'active' && !u.is_active) return false;
        if (this.staffStatusTab === 'inactive' && u.is_active) return false;
        if (this.staffRoleFilter && u.role !== this.staffRoleFilter) return false;
        if (!q) return true;
        return `${u.full_name || ''} ${u.email || ''} ${u.username || ''} ${u.role || ''}`.toLowerCase().includes(q);
      });
    },

    toggleRevealLogin(uid) {
      this.revealedIdMap = { ...this.revealedIdMap, [uid]: !this.revealedIdMap[uid] };
    },

    openNewStaffModal() {
      this.userForm = { id: null, full_name: '', email: '', username: '', password: '', role: 'cashier', is_active: true };
      this.staffModalOpen = true;
    },

    openEditStaffModal(u) {
      this.userForm = {
        id: u.id,
        full_name: u.full_name || '',
        email: u.email || '',
        username: u.username || '',
        password: '',
        role: u.role || 'cashier',
        is_active: Boolean(u.is_active),
      };
      this.staffModalOpen = true;
    },

    async saveStaff() {
      const f = this.userForm;
      if (!f.full_name.trim() || (!f.id && !f.email.trim())) {
        this.notify('Full name and email are required.', 'error');
        return;
      }
      await this._runAction('busy', async () => {
        if (f.id) {
          const patch = { full_name: f.full_name.trim(), role: f.role, is_active: Boolean(f.is_active) };
          if (f.password) patch.password = f.password;
          await this.api(`/users/${f.id}`, { method: 'PATCH', body: JSON.stringify(patch) });
        } else {
          await this.api('/users', {
            method: 'POST',
            body: JSON.stringify({
              full_name: f.full_name.trim(),
              email: f.email.trim(),
              username: f.username.trim() || null,
              password: f.password || null,
              role: f.role,
              is_active: Boolean(f.is_active),
            }),
          });
        }
        this.staffModalOpen = false;
        await this.loadUsers();
      }, f.id ? 'Staff account updated.' : 'Staff user created.');
    },

    async toggleUserActive(u) {
      await this._runAction('busy', async () => {
        if (u.is_active) {
          await this.api(`/users/${u.id}`, { method: 'DELETE' });
        } else {
          await this.api(`/users/${u.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: true }) });
        }
        await this.loadUsers();
      }, u.is_active ? 'User deactivated.' : 'User activated.');
    },
  };
}
