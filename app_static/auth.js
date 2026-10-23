/* Ped Bot sign-in. Session ticket only in localStorage; profiles live in Supabase. */
(function () {
  const TICKET = 'pedro.auth.ticket';
  const PKCE = 'pedro.auth.pkce';
  const rawFetch = window.fetch.bind(window);
  let cfg = null;
  let token = '';
  let ready = false;
  const waiters = [];
  const $ = (s, root) => (root || document).querySelector(s);

  function localApi(url) {
    try {
      const u = new URL(String((url && url.url) || url), location.href);
      if (u.origin !== location.origin) return false;
      const p = u.pathname;
      if (p === '/api/auth/config') return false;
      return p.indexOf('/api/') === 0 || p.indexOf('/live/') === 0;
    } catch (e) { return false; }
  }

  function withAuth(u, o) {
    o = Object.assign({}, o || {});
    const headers = new Headers(o.headers || {});
    if (token && !headers.has('Authorization')) headers.set('Authorization', 'Bearer ' + token);
    o.headers = headers;
    return rawFetch(u, o);
  }

  window.fetch = function (u, o) {
    if (ready || !localApi(u)) return withAuth(u, o);
    return new Promise((resolve, reject) => { waiters.push({ u, o, resolve, reject }); });
  };

  function flush() {
    ready = true;
    const q = waiters.splice(0);
    q.forEach((item) => { withAuth(item.u, item.o).then(item.resolve, item.reject); });
  }

  function loadTicket() {
    try { return JSON.parse(localStorage.getItem(TICKET) || 'null'); } catch (e) { return null; }
  }
  function saveTicket(sess) {
    if (!sess || !sess.access_token) { localStorage.removeItem(TICKET); token = ''; return; }
    const row = {
      access_token: sess.access_token,
      refresh_token: sess.refresh_token || '',
      expires_at: sess.expires_at || (Math.floor(Date.now() / 1000) + Number(sess.expires_in || 3600))
    };
    localStorage.setItem(TICKET, JSON.stringify(row));
    token = row.access_token;
  }
  function clearTicket() { localStorage.removeItem(TICKET); token = ''; }

  function sbHeaders(extra) {
    const h = { apikey: cfg.anonKey, 'Content-Type': 'application/json' };
    if (token) h.Authorization = 'Bearer ' + token;
    else if (cfg.anonKey) h.Authorization = 'Bearer ' + cfg.anonKey;
    return Object.assign(h, extra || {});
  }

  async function sb(path, opt) {
    const res = await rawFetch(cfg.url + path, Object.assign({ headers: sbHeaders() }, opt || {}));
    let data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    return { res, data };
  }

  function friendly(data, fallback) {
    const msg = String((data && (data.error_description || data.msg || data.error || data.message)) || fallback || 'Something went wrong.');
    const low = msg.toLowerCase();
    if (low.indexOf('already registered') >= 0 || low.indexOf('user already') >= 0) return 'This email is already registered. Sign in instead.';
    if (low.indexOf('invalid login') >= 0 || low.indexOf('invalid credentials') >= 0) return 'Wrong email or password.';
    if (low.indexOf('email not confirmed') >= 0) return 'Check your email to confirm this account, then sign in.';
    if (low.indexOf('at least 6') >= 0) return 'Password must be at least 6 characters.';
    if (low.indexOf('invalid format') >= 0 || low.indexOf('valid email') >= 0) return 'Enter a valid email address.';
    if (low.indexOf('signup is disabled') >= 0) return 'Sign up is disabled in the Supabase project.';
    return msg;
  }

  function showGate() {
    document.documentElement.classList.add('auth-boot');
    const gate = $('#auth-gate');
    if (gate) gate.hidden = false;
  }
  function hideGate() {
    document.documentElement.classList.remove('auth-boot');
    const gate = $('#auth-gate');
    if (gate) gate.hidden = true;
  }
  function setErr(text) {
    const el = $('#auth-err');
    if (el) el.textContent = text || '';
  }
  function modeSignup(on) {
    const form = $('#auth-form');
    const title = $('#auth-title');
    const sub = $('#auth-sub');
    const submit = $('#auth-submit');
    const sw = $('#auth-switch');
    const nameWrap = $('#auth-name-wrap');
    if (form) form.dataset.mode = on ? 'signup' : 'login';
    if (title) title.textContent = on ? 'Create account' : 'Sign in';
    if (sub) sub.textContent = on ? 'New accounts start on the free plan.' : 'Email and password. Your data stays in your database.';
    if (submit) submit.textContent = on ? 'Create account' : 'Sign in';
    if (sw) sw.textContent = on ? 'Already have an account? Sign in' : 'Create an account';
    if (nameWrap) nameWrap.hidden = !on;
    setErr('');
  }

  function showSetup(missing) {
    showGate();
    const setup = $('#auth-setup');
    const form = $('#auth-form');
    const oauth = $('#auth-oauth');
    const sw = $('#auth-switch');
    const title = $('#auth-title');
    const sub = $('#auth-sub');
    if (title) title.textContent = 'Connect Supabase';
    if (sub) sub.textContent = 'Accounts live in your Supabase project, not in this app.';
    if (form) form.hidden = true;
    if (oauth) oauth.hidden = true;
    if (sw) sw.hidden = true;
    if (setup) {
      setup.hidden = false;
      const keys = (missing && missing.length) ? missing.join(', ') : 'SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY';
      setup.innerHTML =
        '<ol>' +
        '<li>Create a project at <a href="https://supabase.com/dashboard" target="_blank" rel="noreferrer">supabase.com/dashboard</a>.</li>' +
        '<li>SQL Editor → paste <code>PedroAgent\\supabase\\schema.sql</code> → Run.</li>' +
        '<li>Authentication → URL Configuration: Site URL <code>http://127.0.0.1:8765</code>, Redirect URLs <code>http://127.0.0.1:8765/</code>.</li>' +
        '<li>Email provider: turn Confirm email off for this desktop app (or leave it on and confirm from your inbox).</li>' +
        '<li>Project Settings → API: copy the URL, anon key, and service role key into <code>.env</code>.</li>' +
        '<li>Set <code>ADMIN_EMAIL</code> to your email so you can open Users.</li>' +
        '<li>Quit Ped Bot from the tray and start it again.</li>' +
        '</ol>' +
        '<p class="auth-missing">Missing: ' + keys + '</p>';
    }
  }

  function paintOauth() {
    const box = $('#auth-oauth');
    if (!box || !cfg) return;
    const g = $('#auth-google');
    const h = $('#auth-github');
    const any = !!(cfg.oauthGoogle || cfg.oauthGithub);
    box.hidden = !any;
    if (g) g.hidden = !cfg.oauthGoogle;
    if (h) h.hidden = !cfg.oauthGithub;
  }

  async function refreshIfNeeded(sess) {
    if (!sess || !sess.refresh_token) return sess;
    const exp = Number(sess.expires_at || 0);
    if (exp && exp * 1000 > Date.now() + 60000) return sess;
    const { res, data } = await sb('/auth/v1/token?grant_type=refresh_token', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: sess.refresh_token })
    });
    if (!res.ok || !data.access_token) return sess;
    saveTicket(data);
    return loadTicket();
  }

  async function afterSession() {
    const me = await withAuth('/api/auth/me').then((r) => r.json()).catch(() => null);
    if (!me || !me.ok || !me.user) return false;
    const adminBtn = $('#acct-admin');
    if (adminBtn) adminBtn.hidden = !me.user.is_admin;
    const who = $('#auth-who');
    if (who) who.textContent = me.user.email || '';
    hideGate();
    flush();
    return true;
  }

  async function signIn(email, password) {
    const { res, data } = await sb('/auth/v1/token?grant_type=password', {
      method: 'POST',
      body: JSON.stringify({ email, password })
    });
    if (!res.ok || !data.access_token) throw new Error(friendly(data, 'Could not sign in.'));
    saveTicket(data);
    if (!(await afterSession())) throw new Error('Signed in, but the profile could not be loaded. Check schema.sql was run.');
  }

  async function signUp(email, password, fullName) {
    const { res, data } = await sb('/auth/v1/signup', {
      method: 'POST',
      body: JSON.stringify({ email, password, data: { full_name: fullName || '' } })
    });
    if (!res.ok) throw new Error(friendly(data, 'Could not create the account.'));
    if (data && data.access_token) {
      saveTicket(data);
      if (!(await afterSession())) throw new Error('Account created, but the profile could not be loaded. Check schema.sql was run.');
      return;
    }
    throw new Error('Check your email to confirm this account, then sign in.');
  }

  function b64url(bytes) {
    let s = '';
    const arr = new Uint8Array(bytes);
    for (let i = 0; i < arr.length; i++) s += String.fromCharCode(arr[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  async function makePkce() {
    const raw = crypto.getRandomValues(new Uint8Array(32));
    const verifier = b64url(raw);
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    sessionStorage.setItem(PKCE, verifier);
    return { verifier, challenge: b64url(digest) };
  }

  async function startOauth(provider) {
    const redirect = location.origin + '/';
    let url = cfg.url + '/auth/v1/authorize?provider=' + encodeURIComponent(provider) +
      '&redirect_to=' + encodeURIComponent(redirect);
    try {
      const pk = await makePkce();
      url += '&code_challenge=' + encodeURIComponent(pk.challenge) + '&code_challenge_method=S256';
    } catch (e) { /* WebView without subtle: implicit hash tokens still work if enabled. */ }
    location.href = url;
  }

  async function consumeOauth() {
    const hash = new URLSearchParams((location.hash || '').replace(/^#/, ''));
    const query = new URLSearchParams(location.search || '');
    const err = hash.get('error_description') || query.get('error_description') || query.get('error');
    if (err) {
      history.replaceState({}, '', location.pathname + (location.search.replace(/[?&](code|error|error_description)=[^&]*/g, '').replace(/^&/, '?')) );
      location.hash = '';
      throw new Error(err);
    }
    const access = hash.get('access_token');
    if (access) {
      saveTicket({
        access_token: access,
        refresh_token: hash.get('refresh_token') || '',
        expires_in: hash.get('expires_in')
      });
      location.hash = '';
      return afterSession();
    }
    const code = query.get('code');
    if (!code) return false;
    const verifier = sessionStorage.getItem(PKCE) || '';
    sessionStorage.removeItem(PKCE);
    const { res, data } = await sb('/auth/v1/token?grant_type=pkce', {
      method: 'POST',
      body: JSON.stringify({ auth_code: code, code_verifier: verifier })
    });
    history.replaceState({}, '', location.pathname);
    if (!res.ok || !data.access_token) throw new Error(friendly(data, 'Google / GitHub sign-in did not finish.'));
    saveTicket(data);
    return afterSession();
  }

  async function logout() {
    try {
      if (cfg && cfg.url && token) {
        await rawFetch(cfg.url + '/auth/v1/logout', { method: 'POST', headers: sbHeaders() });
      }
    } catch (e) { /* still clear local ticket */ }
    clearTicket();
    location.reload();
  }

  async function loadAdmin() {
    const body = $('#admin-body');
    const count = $('#admin-count');
    if (body) body.innerHTML = '<p class="auth-muted">Loading…</p>';
    const r = await fetch('/api/admin/users');
    const d = await r.json().catch(() => ({}));
    if (!d.ok) {
      if (body) body.innerHTML = '<p class="auth-err">' + (d.error || 'Could not load users.') + '</p>';
      return;
    }
    if (count) count.textContent = String(d.count || 0) + ' signup' + ((d.count === 1) ? '' : 's');
    const rows = d.users || [];
    if (!rows.length) {
      if (body) body.innerHTML = '<p class="auth-muted">No users yet.</p>';
      return;
    }
    const fmt = (v) => {
      if (!v) return '—';
      const dt = new Date(v);
      return isNaN(dt.getTime()) ? String(v) : dt.toLocaleString();
    };
    let html = '<table class="admin-table"><thead><tr><th>Email</th><th>Name</th><th>Signed up</th><th>Plan</th></tr></thead><tbody>';
    rows.forEach((u) => {
      html += '<tr><td>' + escapeHtml(u.email || '') + '</td><td>' + escapeHtml(u.full_name || '—') +
        '</td><td>' + escapeHtml(fmt(u.created_at)) + '</td><td>' + escapeHtml(u.subscription_status || 'free') + '</td></tr>';
    });
    html += '</tbody></table>';
    if (body) body.innerHTML = html;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function bind() {
    const form = $('#auth-form');
    const sw = $('#auth-switch');
    const google = $('#auth-google');
    const github = $('#auth-github');
    const logoutBtn = $('#acct-logout');
    const adminBtn = $('#acct-admin');
    const adminOv = $('#admin-ov');
    const adminClose = $('#admin-close');
    if (sw) sw.onclick = () => modeSignup(form && form.dataset.mode !== 'signup');
    if (form) form.onsubmit = async (e) => {
      e.preventDefault();
      setErr('');
      const email = ($('#auth-email') && $('#auth-email').value || '').trim();
      const password = ($('#auth-pass') && $('#auth-pass').value) || '';
      const name = ($('#auth-name') && $('#auth-name').value || '').trim();
      const signup = form.dataset.mode === 'signup';
      const submit = $('#auth-submit');
      if (submit) submit.disabled = true;
      try {
        if (signup) await signUp(email, password, name);
        else await signIn(email, password);
      } catch (err) {
        setErr(err.message || 'Could not sign in.');
      } finally {
        if (submit) submit.disabled = false;
      }
    };
    if (google) google.onclick = () => startOauth('google');
    if (github) github.onclick = () => startOauth('github');
    if (logoutBtn) logoutBtn.onclick = () => logout();
    if (adminBtn) adminBtn.onclick = () => {
      if (adminOv) adminOv.hidden = false;
      loadAdmin();
    };
    if (adminClose) adminClose.onclick = () => { if (adminOv) adminOv.hidden = true; };
    if (adminOv) adminOv.onclick = (e) => { if (e.target === adminOv) adminOv.hidden = true; };
  }

  window.PedroAuth = {
    onUnauthorized: function () {
      clearTicket();
      showGate();
      modeSignup(false);
      setErr('Please sign in again.');
    },
    logout: logout,
    user: function () { return loadTicket(); }
  };

  async function boot() {
    bind();
    modeSignup(false);
    try {
      if (typeof PedroNative !== 'undefined' && PedroNative.ticket) {
        const raw = PedroNative.ticket();
        if (raw) saveTicket(JSON.parse(raw));
      }
    } catch (e) { /* desktop window has no native bridge */ }
    try {
      cfg = await rawFetch('/api/auth/config').then((r) => r.json());
    } catch (e) {
      showSetup(['SUPABASE_URL']);
      return;
    }
    if (!cfg || !cfg.configured) {
      showSetup(cfg && cfg.missing);
      return;
    }
    paintOauth();
    try {
      if (await consumeOauth()) return;
    } catch (e) {
      showGate();
      setErr(e.message || 'Sign-in did not finish.');
      return;
    }
    let sess = loadTicket();
    if (sess && sess.access_token) {
      token = sess.access_token;
      try { sess = await refreshIfNeeded(sess); } catch (e) { /* try the old ticket */ }
      if (sess && sess.access_token) token = sess.access_token;
      if (await afterSession()) return;
      clearTicket();
    }
    showGate();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
