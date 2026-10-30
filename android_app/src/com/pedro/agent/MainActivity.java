package com.pedro.agent;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.*;
import android.speech.*;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends Activity {
    static final String PREFS = "pedro", CH = "pedro_replies";
    WebView web; LinearLayout errorView; TextView errText;
    SharedPreferences prefs; PermissionRequest pendingWebPerm; ValueCallback<Uri[]> fileCb;
    SpeechRecognizer stt; boolean resumed, showingAuth, refreshedThisTry, inPhone;
    SecureStore secure;

    @Override protected void onCreate(Bundle b) {
        setTheme(android.R.style.Theme_Material_NoActionBar);
        super.onCreate(b);
        getWindow().setStatusBarColor(Color.parseColor("#0e0f11"));
        getWindow().setNavigationBarColor(Color.parseColor("#0e0f11"));
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        secure = new SecureStore(prefs);
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel c = new NotificationChannel(CH, "Agent replies", NotificationManager.IMPORTANCE_DEFAULT);
            getSystemService(NotificationManager.class).createNotificationChannel(c);
        }
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#0e0f11"));
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        errorView = buildError(); root.addView(errorView, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);
        configureWeb();
        String shared = getIntent() != null ? getIntent().getStringExtra(Intent.EXTRA_TEXT) : null;
        if (shared != null && shared.contains("http")) { saveLink(shared, ""); }
        else if (!prefs.getString("ticket", "").isEmpty() || !prefs.getString("base", "").isEmpty()) autoConnect();
        else showAuth();
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 3);
    }

    @Override protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        String s = i.getStringExtra(Intent.EXTRA_TEXT);
        if (s != null && s.contains("http")) saveLink(s, "");
    }

    void showAuth() {
        showingAuth = true; inPhone = false;
        errorView.setVisibility(View.GONE);
        try {
            String html = readRaw(R.raw.auth_setup)
                .replace("{{URL}}", JSONObject.quote(Config.SUPABASE_URL))
                .replace("{{ANON}}", JSONObject.quote(Config.ANON_KEY));
            web.loadDataWithBaseURL(Config.SUPABASE_URL + "/", html, "text/html", "UTF-8", null);
        } catch (Exception e) {
            showError("Could not open sign-in.");
        }
    }

    LinearLayout buildError() {
        LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.VERTICAL); l.setGravity(Gravity.CENTER);
        l.setBackgroundColor(Color.parseColor("#0e0f11")); int p = dp(24); l.setPadding(p, p, p, p);
        ImageView logo = new ImageView(this); logo.setImageResource(R.drawable.splash_icon);
        l.addView(logo, new LinearLayout.LayoutParams(dp(96), dp(96)));
        errText = text("Can't reach your PC.", 16, "#e7e9ea"); errText.setGravity(Gravity.CENTER); l.addView(errText);
        TextView hint = text("Is Ped Bot running on your PC with Connect phone turned on?", 14, "#8b9096");
        hint.setGravity(Gravity.CENTER); l.addView(hint);
        Button retry = grokBtn("Try again", true); retry.setOnClickListener(v -> autoConnect()); l.addView(retry);
        Button phone = grokBtn("Use phone mode", false); phone.setOnClickListener(v -> showPhoneMode("PC offline")); l.addView(phone);
        Button again = grokBtn("Sign in again", false); again.setOnClickListener(v -> { prefs.edit().remove("base").apply(); showAuth(); }); l.addView(again);
        l.setVisibility(View.GONE); return l;
    }

    void configureWeb() {
        WebSettings s = web.getSettings();
        // 1.6.3: locked app shell - no pinch/zoom-out, no overscroll glow/bounce, font scaling can't widen the page
        s.setSupportZoom(false); s.setBuiltInZoomControls(false); s.setDisplayZoomControls(false);
        s.setUseWideViewPort(true); s.setLoadWithOverviewMode(false); s.setTextZoom(100);
        web.setOverScrollMode(android.view.View.OVER_SCROLL_NEVER);
        web.setHorizontalScrollBarEnabled(false);
        s.setJavaScriptEnabled(true); s.setDomStorageEnabled(true); s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false); s.setAllowFileAccess(false);
        s.setUserAgentString(s.getUserAgentString() + " PedroAgentApp/1.1");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setBackgroundColor(Color.parseColor("#0e0f11"));
        web.addJavascriptInterface(new Bridge(), "PedroNative");
        // 1.6.6: downloads. The WebView had no DownloadListener, so chat "Download" links did nothing.
        web.setDownloadListener((url, ua, disposition, mime, length) -> saveToDownloads(url, disposition, mime));
        web.setOnLongClickListener(v -> {
            WebView.HitTestResult h = web.getHitTestResult();
            if (h == null) return false;
            int t = h.getType();
            if (t != WebView.HitTestResult.IMAGE_TYPE && t != WebView.HitTestResult.SRC_IMAGE_ANCHOR_TYPE) return false;
            String src = h.getExtra(); if (src == null || !src.startsWith("http")) return false;
            new AlertDialog.Builder(this).setItems(new String[]{"Save image", "Share link"}, (d, which) -> {
                if (which == 0) saveToDownloads(src + (src.contains("?") ? "&" : "?") + "download=1", null, null);
                else { Intent i = new Intent(Intent.ACTION_SEND); i.setType("text/plain"); i.putExtra(Intent.EXTRA_TEXT, src); startActivity(Intent.createChooser(i, "Share")); }
            }).show();
            return true;
        });
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl(); String base = prefs.getString("base", "");
                if (showingAuth) {
                    String host = u.getHost();
                    if (host != null && Config.SUPABASE_URL.contains(host)) return false;
                }
                if (inPhone && "phone.pedbot.local".equals(u.getHost())) return false;
                if (inPhone) { try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) {} return true; }
                if (!base.isEmpty() && u.toString().startsWith(base)) return false;
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) {}
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                if (inPhone && "phone.pedbot.local".equals(u.getHost())) return phoneAsset(u);
                return null;
            }
            @Override public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame() && !showingAuth && !inPhone) failOrRefresh("Can't reach your PC (" + e.getDescription() + ").");
            }
            @Override public void onReceivedHttpError(WebView v, WebResourceRequest r, WebResourceResponse resp) {
                if (showingAuth || inPhone || !r.isForMainFrame()) return;
                if (resp.getStatusCode() == 530 || resp.getStatusCode() == 502 || (resp.getStatusCode() == 404 && r.getUrl().getHost() != null && r.getUrl().getHost().endsWith("trycloudflare.com")))
                    failOrRefresh("That link has expired (" + resp.getStatusCode() + "). Ped Bot will publish a new one when it is running.");
            }
            @Override public void onPageFinished(WebView v, String url) {
                CookieManager.getInstance().flush();
                refreshedThisTry = false;
                if (!showingAuth) v.evaluateJavascript(INJECT, null);
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest req) {
                runOnUiThread(() -> {
                    if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) req.grant(req.getResources());
                    else { pendingWebPerm = req; requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1); }
                });
            }
            @Override public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (fileCb != null) fileCb.onReceiveValue(null); fileCb = cb;
                try { startActivityForResult(p.createIntent(), 9); } catch (Exception e) { fileCb = null; return false; }
                return true;
            }
        });
    }

    void openServer() {
        String base = prefs.getString("base", "");
        if (base.isEmpty()) { showAuth(); return; }
        showingAuth = false; inPhone = false;
        errorView.setVisibility(View.GONE);
        String secret = prefs.getString("secret", "");
        if (!secret.isEmpty() && prefs.getString("ticket", "").isEmpty())
            web.loadUrl(base + "/login#t=" + Uri.encode(secret));
        else
            web.loadUrl(base + "/?ui=grokskin");
    }

    void onSession(String json) {
        try {
            JSONObject sess = new JSONObject(json);
            if (!sess.has("access_token") || sess.optString("access_token").isEmpty()) {
                toast("Could not sign in."); return;
            }
            prefs.edit().putString("ticket", sess.toString()).apply();
            connectWithAccount();
        } catch (Exception e) { toast("Could not sign in."); }
    }

    void saveLink(String raw, String secret) {
        raw = (raw == null ? "" : raw).trim();
        int i = raw.indexOf("http"); if (i > 0) raw = raw.substring(i);
        int sp = raw.indexOf(' '); if (sp > 0) raw = raw.substring(0, sp);
        if (!raw.startsWith("http")) raw = "https://" + raw;
        String base = baseFrom(raw);
        if (secret == null) secret = "";
        secret = secret.trim();
        if (secret.isEmpty()) secret = tokenFrom(raw);
        if (base.isEmpty()) { toast("That link doesn't look right"); return; }
        SharedPreferences.Editor e = prefs.edit().putString("base", base);
        if (!secret.isEmpty()) e.putString("secret", secret);
        e.apply();
        CookieManager.getInstance().removeAllCookies(null);
        showingAuth = false;
        openServer();
    }

    void autoConnect() {
        refreshedThisTry = true;
        if (!prefs.getString("ticket", "").isEmpty()) { connectWithAccount(); return; }
        String secret = prefs.getString("secret", "");
        if (secret.isEmpty() && prefs.getString("base", "").isEmpty()) { showAuth(); return; }
        new Thread(() -> {
            String url = fetchPublished(secret);
            runOnUiThread(() -> {
                if (!url.isEmpty() && !url.equals(prefs.getString("base", ""))) {
                    prefs.edit().putString("base", url).apply();
                    CookieManager.getInstance().removeAllCookies(null);
                    toast("Connected to your PC's new link");
                }
                openServer();
            });
        }).start();
    }

    void connectWithAccount() {
        showingAuth = false;
        errorView.setVisibility(View.GONE);
        if (prefs.getBoolean("phone_only", false)) { showPhoneMode("Phone mode"); return; }
        toast("Finding your PC…");
        new Thread(() -> {
            try {
                JSONObject sess = refreshIfNeeded(new JSONObject(prefs.getString("ticket", "{}")));
                prefs.edit().putString("ticket", sess.toString()).apply();
                String access = sess.getString("access_token");
                // 1.6.5: the PC's free tunnel gets a NEW link on every restart and needs ~10-40 s
                // to come up, so look a few times before falling back to phone mode.
                String url = "";
                for (int i = 0; i < 4; i++) {
                    url = fetchPresence(access);
                    if (!url.isEmpty() && pcOnline(url)) break;
                    url = "";
                    if (i < 3) Thread.sleep(4000);
                }
                // 1.5.12: prefer the PC when it answers; otherwise run the bots on the phone.
                if (url.isEmpty()) {
                    runOnUiThread(() -> showPhoneMode("PC offline"));
                    return;
                }
                String cookie = loginWithJwt(url, access);
                if (cookie != null && !cookie.isEmpty()) CookieManager.getInstance().setCookie(url, cookie);
                CookieManager.getInstance().flush();
                prefs.edit().putString("base", url).apply();
                runOnUiThread(this::openServer);
            } catch (Exception e) {
                showError(e.getMessage() != null ? e.getMessage() : "Can't reach your PC.");
            }
        }).start();
    }

    JSONObject refreshIfNeeded(JSONObject sess) throws Exception {
        String refresh = sess.optString("refresh_token", "");
        long exp = sess.optLong("expires_at", 0);
        if (refresh.isEmpty() || (exp > 0 && exp * 1000 > System.currentTimeMillis() + 60000)) return sess;
        JSONObject body = new JSONObject(); body.put("refresh_token", refresh);
        HttpResult r = http("POST", Config.SUPABASE_URL + "/auth/v1/token?grant_type=refresh_token",
            body.toString(), Config.ANON_KEY, Config.ANON_KEY);
        JSONObject data = new JSONObject(r.body);
        if (r.code >= 400 || !data.has("access_token")) throw new Exception("Please sign in again.");
        if (!data.has("expires_at"))
            data.put("expires_at", (System.currentTimeMillis() / 1000) + data.optLong("expires_in", 3600));
        return data;
    }

    String fetchPresence(String access) throws Exception {
        HttpResult r = http("GET", Config.SUPABASE_URL + "/rest/v1/pc_presence?id=eq.default&select=url,updated_at",
            null, access, Config.ANON_KEY);
        if (r.code >= 400) throw new Exception("Could not look up your PC.");
        JSONArray rows = new JSONArray(r.body);
        if (rows.length() == 0) return "";
        String url = rows.getJSONObject(0).optString("url", "").trim().replaceAll("/+$", "");
        return url.startsWith("https://") ? url : "";
    }

    String loginWithJwt(String base, String access) throws Exception {
        JSONObject body = new JSONObject(); body.put("access_token", access);
        HttpResult r = http("POST", base + "/login", body.toString(), null, null);
        if (r.code >= 400) throw new Exception("Signed in, but this PC did not accept the account.");
        if (r.cookies == null) return null;
        for (String c : r.cookies) {
            if (c != null && c.startsWith("pedro_session=")) {
                int cut = c.indexOf(';');
                return (cut > 0 ? c.substring(0, cut) : c) + "; Path=/";
            }
        }
        return null;
    }

    static boolean pcOnline(String base) {
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(base + "/login").openConnection();
            c.setConnectTimeout(5000); c.setReadTimeout(5000); c.setInstanceFollowRedirects(false);
            int code = c.getResponseCode(); c.disconnect();
            return code > 0 && code < 500;
        } catch (Exception e) { return false; }
    }

    /** 1.5.13 phone-only mode: the PC's own web UI, bundled in the APK (assets/web), with /api answered on the phone. */
    static final String PHONE_ORIGIN = "https://phone.pedbot.local";
    String phoneReason = "PC offline";
    void showPhoneMode(String reason) {
        runOnUiThread(() -> {
            if (prefs.getString("ticket", "").isEmpty()) { showAuth(); return; }
            showingAuth = false; inPhone = true; phoneReason = reason == null ? "PC offline" : reason;
            errorView.setVisibility(View.GONE);
            web.loadUrl(PHONE_ORIGIN + "/?ui=grokskin");
            watchForPc();
        });
    }

    /** 1.6.5: while in phone mode (not chosen by hand), keep checking for the PC and switch to it when it comes online. */
    boolean watching;
    void watchForPc() {
        if (watching || prefs.getBoolean("phone_only", false)) return;
        watching = true;
        new Thread(() -> {
            try {
                while (inPhone && !prefs.getBoolean("phone_only", false)) {
                    Thread.sleep(20000);
                    if (!resumed) continue;
                    try {
                        JSONObject sess = refreshIfNeeded(new JSONObject(prefs.getString("ticket", "{}")));
                        prefs.edit().putString("ticket", sess.toString()).apply();
                        String url = fetchPresence(sess.getString("access_token"));
                        if (!url.isEmpty() && pcOnline(url)) {
                            runOnUiThread(() -> { toast("Your PC is online - connecting"); connectWithAccount(); });
                            break;
                        }
                    } catch (Exception ignored) {}
                }
            } catch (InterruptedException ignored) {
            } finally { watching = false; }
        }).start();
    }

    static String mimeOf(String path) {
        String p = path.toLowerCase();
        if (p.endsWith(".html")) return "text/html"; if (p.endsWith(".js")) return "application/javascript";
        if (p.endsWith(".css")) return "text/css"; if (p.endsWith(".png")) return "image/png"; if (p.endsWith(".svg")) return "image/svg+xml";
        if (p.endsWith(".ico")) return "image/x-icon"; if (p.endsWith(".webp")) return "image/webp"; if (p.endsWith(".json") || p.endsWith(".webmanifest")) return "application/json";
        if (p.endsWith(".woff2")) return "font/woff2"; if (p.endsWith(".mp3")) return "audio/mpeg";
        return "application/octet-stream";
    }

    /** Serves the bundled UI for https://phone.pedbot.local/... ; /api/* is answered by phone_shim.js before it gets here. */
    WebResourceResponse phoneAsset(Uri u) {
        String path = u.getPath() == null || u.getPath().equals("/") ? "/index.html" : u.getPath();
        if (path.contains("..")) return null;
        try {
            if (path.equals("/index.html")) {
                JSONObject cfg = new JSONObject();
                cfg.put("url", Config.SUPABASE_URL); cfg.put("anon", Config.ANON_KEY); cfg.put("reason", phoneReason);
                String head = "<script>window.__PB_PHONE=" + cfg.toString() + ";</script>"
                    + "<script src=\"/phone_core.js\"></script><script src=\"/phone_shim.js\"></script>";
                String html = readStream(getAssets().open("web/index.html"));
                int i = html.indexOf("<script");
                html = i < 0 ? head + html : html.substring(0, i) + head + html.substring(i);
                return new WebResourceResponse("text/html", "UTF-8", new java.io.ByteArrayInputStream(html.getBytes("UTF-8")));
            }
            return new WebResourceResponse(mimeOf(path), "UTF-8", getAssets().open("web" + path));
        } catch (Exception e) {
            WebResourceResponse r = new WebResourceResponse("text/plain", "UTF-8", new java.io.ByteArrayInputStream(new byte[0]));
            r.setStatusCodeAndReasonPhrase(404, "Not found"); return r;
        }
    }

    void geminiModels(String cb) {
        new Thread(() -> {
            int code = 0; String out;
            try {
                String key = secure.get();
                if (key.isEmpty()) throw new Exception("Add your Gemini key first.");
                HttpURLConnection c = (HttpURLConnection) new URL("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200").openConnection();
                c.setConnectTimeout(15000); c.setReadTimeout(30000);
                c.setRequestProperty("x-goog-api-key", key);
                code = c.getResponseCode();
                out = readStream(code >= 400 ? c.getErrorStream() : c.getInputStream());
            } catch (Exception e) { out = "{}"; }
            final String js = "window.__pbGemini&&window.__pbGemini(" + JSONObject.quote(cb) + "," + code + "," + JSONObject.quote(out) + ")";
            runOnUiThread(() -> web.evaluateJavascript(js, null));
        }).start();
    }

    static final java.util.regex.Pattern MODEL_OK = java.util.regex.Pattern.compile("^gemini-[a-z0-9.\\-]{1,40}$");

    void gemini(String model, String body, String cb) {
        new Thread(() -> {
            int code = 0; String out;
            try {
                String key = secure.get();
                if (key.isEmpty()) throw new Exception("Add your Gemini key first.");
                if (!MODEL_OK.matcher(model).matches()) throw new Exception("Bad model name.");
                HttpURLConnection c = (HttpURLConnection) new URL("https://generativelanguage.googleapis.com/v1beta/models/"
                    + model + ":generateContent").openConnection();
                c.setConnectTimeout(15000); c.setReadTimeout(90000); c.setRequestMethod("POST");
                c.setRequestProperty("Content-Type", "application/json");
                c.setRequestProperty("x-goog-api-key", key);
                byte[] raw = body.getBytes("UTF-8"); c.setDoOutput(true); c.setFixedLengthStreamingMode(raw.length);
                c.getOutputStream().write(raw);
                code = c.getResponseCode();
                out = readStream(code >= 400 ? c.getErrorStream() : c.getInputStream());
            } catch (Exception e) {
                JSONObject err = new JSONObject();
                try { err.put("error", new JSONObject().put("message", String.valueOf(e.getMessage()))); } catch (Exception ignored) {}
                out = err.toString();
            }
            final String js = "window.__pbGemini&&window.__pbGemini(" + JSONObject.quote(cb) + "," + code + "," + JSONObject.quote(out) + ")";
            runOnUiThread(() -> web.evaluateJavascript(js, null));
        }).start();
    }

    String session() {
        try {
            JSONObject sess = refreshIfNeeded(new JSONObject(prefs.getString("ticket", "{}")));
            prefs.edit().putString("ticket", sess.toString()).apply();
            JSONObject out = new JSONObject();
            out.put("access_token", sess.optString("access_token"));
            JSONObject user = sess.optJSONObject("user");
            out.put("user_id", user != null ? user.optString("id") : "");
            return out.toString();
        } catch (Exception e) { return "{}"; }
    }

    void failOrRefresh(String msg) {
        if (refreshedThisTry) { refreshedThisTry = false; showError(msg); return; }
        autoConnect();
    }

    void showError(String msg) { runOnUiThread(() -> { errText.setText(msg); errorView.setVisibility(View.VISIBLE); }); }

    static final String INJECT = "(function(){if(window.__pedroApp)return;window.__pedroApp=1;"
        + "var of=window.fetch,lastRe=0;window.fetch=function(u,o){return of.apply(this,arguments).then(function(r){"
        + "var ct=(r.headers.get('content-type')||'');"
        + "var api=String(u&&u.url||u).indexOf('/api')>=0||(o&&o.method&&o.method!='GET');"
        + "if(api&&(r.status==401||r.status==502||r.status==530||(r.status>=500&&ct.indexOf('json')<0)||(r.status>=400&&ct.indexOf('text/html')>=0))){"
        + "if(Date.now()-lastRe>15000){lastRe=Date.now();PedroNative.reauth();}"
        + "throw new Error('Reconnecting to your PC, try again in a few seconds');}return r;});};"
        + "if(location.pathname==='/login'){var f=document.querySelector('form');if(f&&!document.getElementById('pa-x')){var a=document.createElement('a');a.id='pa-x';a.textContent='Use a different account';a.href='#';a.style.cssText='display:block;margin-top:16px;color:#1d9bf0';a.onclick=function(e){e.preventDefault();PedroNative.signOut()};f.after(a)}return;}"
        + "document.addEventListener('click',function(e){var m=e.target.closest&&e.target.closest('#mic');if(!m)return;e.preventDefault();e.stopImmediatePropagation();m.classList.add('on');PedroNative.listen();},true);"
        + "window.__pedroHeard=function(t){var b=document.getElementById('mic');if(b)b.classList.remove('on');if(!t)return;var x=document.getElementById('t');if(!x)return;x.value=t;x.dispatchEvent(new Event('input',{bubbles:true}));var s=document.getElementById('send');if(s)s.click();};"
        + "var seen=0;function cnt(){return document.querySelectorAll('.msg.bot,.msg.assistant,[data-role=assistant]').length}seen=cnt();"
        + "new MutationObserver(function(){var n=cnt();if(n>seen){seen=n;if(document.hidden){var els=document.querySelectorAll('.msg.bot,.msg.assistant,[data-role=assistant]');var el=els[els.length-1];setTimeout(function(){PedroNative.notify('Ped Bot',(el.innerText||'New reply').slice(0,300))},4000)}}}).observe(document.body,{childList:true,subtree:true});"
        + "})();";

    class Bridge {
        @JavascriptInterface public void onSession(String json) { runOnUiThread(() -> MainActivity.this.onSession(json)); }
        @JavascriptInterface public void saveLink(String raw, String secret) { runOnUiThread(() -> MainActivity.this.saveLink(raw, secret)); }
        @JavascriptInterface public String ticket() { return prefs.getString("ticket", ""); }
        @JavascriptInterface public String supabaseUrl() { return Config.SUPABASE_URL; }
        @JavascriptInterface public String anonKey() { return Config.ANON_KEY; }
        @JavascriptInterface public void reauth() { runOnUiThread(() -> { CookieManager.getInstance().removeAllCookies(null); toast("Reconnecting to your PC…"); autoConnect(); }); }
        @JavascriptInterface public void listen() { runOnUiThread(MainActivity.this::startListening); }
        @JavascriptInterface public void signOut() { runOnUiThread(() -> { prefs.edit().remove("ticket").remove("secret").remove("base").apply(); CookieManager.getInstance().removeAllCookies(null); showAuth(); }); }
        @JavascriptInterface public void newLink() { signOut(); }
        @JavascriptInterface public void notify(String title, String body) { if (!resumed) postNotification(title, body); }
        @JavascriptInterface public String phoneSession() { return session(); }
        @JavascriptInterface public boolean hasGeminiKey() { return secure.has(); }
        @JavascriptInterface public boolean setGeminiKey(String k) {
            k = k == null ? "" : k.trim(); if (k.length() < 20 || k.length() > 200) return false;
            try { secure.put(k); return true; } catch (Exception e) { return false; } }
        @JavascriptInterface public void clearGeminiKey() { secure.clear(); }
        @JavascriptInterface public void gemini(String model, String body, String cb) { MainActivity.this.gemini(model, body, cb); }
        @JavascriptInterface public void geminiModels(String cb) { MainActivity.this.geminiModels(cb); }
        @JavascriptInterface public boolean phoneOnly() { return prefs.getBoolean("phone_only", false); }
        @JavascriptInterface public void setPhoneOnly(boolean on) { prefs.edit().putBoolean("phone_only", on).apply(); }
        @JavascriptInterface public void tryPc() { runOnUiThread(() -> { prefs.edit().putBoolean("phone_only", false).apply(); connectWithAccount(); }); }
    }

    static final String NTFY = "https://ntfy.sh/";
    static String hex(byte[] b) { StringBuilder sb = new StringBuilder(); for (byte x : b) sb.append(String.format("%02x", x)); return sb.toString(); }
    static String fetchPublished(String token) {
        if (token == null || token.length() < 16) return "";
        try {
            String topic = "pedro-" + hex(java.security.MessageDigest.getInstance("SHA-256").digest(("pedro-topic:" + token).getBytes("UTF-8"))).substring(0, 32);
            HttpURLConnection c = (HttpURLConnection) new URL(NTFY + topic + "/json?poll=1&since=all").openConnection();
            c.setConnectTimeout(6000); c.setReadTimeout(6000);
            String body = readStream(c.getInputStream());
            String best = ""; long bestTs = -1;
            javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
            mac.init(new javax.crypto.spec.SecretKeySpec(("pedro-url:" + token).getBytes("UTF-8"), "HmacSHA256"));
            for (String line : body.split("\n")) {
                try {
                    JSONObject ev = new JSONObject(line);
                    if (!"message".equals(ev.optString("event"))) continue;
                    JSONObject d = new JSONObject(ev.optString("message"));
                    String url = d.getString("url"); long ts = d.getLong("ts");
                    String sig = hex(mac.doFinal((url + "|" + ts).getBytes("UTF-8")));
                    if (url.startsWith("https://") && java.security.MessageDigest.isEqual(sig.getBytes(), d.getString("sig").getBytes()) && ts > bestTs) { best = url; bestTs = ts; }
                } catch (Exception ignored) {}
            }
            return best;
        } catch (Exception e) { return ""; }
    }

    static class HttpResult { int code; String body; List<String> cookies; }

    static HttpResult http(String method, String url, String body, String bearer, String apikey) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(12000); c.setReadTimeout(15000);
        c.setRequestMethod(method);
        c.setInstanceFollowRedirects(false);
        c.setRequestProperty("Accept", "application/json");
        if (apikey != null && !apikey.isEmpty()) {
            c.setRequestProperty("apikey", apikey);
            c.setRequestProperty("Authorization", "Bearer " + (bearer != null && !bearer.isEmpty() ? bearer : apikey));
        } else if (bearer != null && !bearer.isEmpty()) {
            c.setRequestProperty("Authorization", "Bearer " + bearer);
        }
        if (body != null) {
            byte[] raw = body.getBytes("UTF-8");
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            c.setFixedLengthStreamingMode(raw.length);
            c.getOutputStream().write(raw);
        }
        HttpResult r = new HttpResult();
        r.code = c.getResponseCode();
        InputStream in = r.code >= 400 ? c.getErrorStream() : c.getInputStream();
        r.body = readStream(in);
        Map<String, List<String>> hdrs = c.getHeaderFields();
        if (hdrs != null) {
            List<String> set = hdrs.get("Set-Cookie");
            if (set == null) set = hdrs.get("set-cookie");
            r.cookies = set;
        }
        return r;
    }

    static String readStream(InputStream in) throws Exception {
        if (in == null) return "";
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[4096]; int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        in.close();
        return out.toString("UTF-8");
    }

    String readRaw(int id) throws Exception { return readStream(getResources().openRawResource(id)); }

    static String tokenFrom(String raw) {
        int h = raw.indexOf('#'); if (h < 0) return "";
        for (String kv : raw.substring(h + 1).split("&")) if (kv.startsWith("t=")) return Uri.decode(kv.substring(2));
        return "";
    }
    static String baseFrom(String raw) {
        Uri u = Uri.parse(raw.trim()); if (u.getScheme() == null || u.getHost() == null) return "";
        String s = u.getScheme() + "://" + u.getHost(); if (u.getPort() > 0) s += ":" + u.getPort(); return s;
    }

    void startListening() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 2); return; }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) { toast("Speech recognition isn't available on this phone"); heard(""); return; }
        if (stt == null) stt = SpeechRecognizer.createSpeechRecognizer(this);
        stt.setRecognitionListener(new RecognitionListener() {
            public void onResults(Bundle r) { ArrayList<String> l = r.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION); heard(l != null && !l.isEmpty() ? l.get(0) : ""); }
            public void onError(int e) { if (e != SpeechRecognizer.ERROR_CLIENT) toast(e == SpeechRecognizer.ERROR_NO_MATCH || e == SpeechRecognizer.ERROR_SPEECH_TIMEOUT ? "Didn't catch that" : "Mic error " + e); heard(""); }
            public void onReadyForSpeech(Bundle p) { toast("Listening…"); }
            public void onBeginningOfSpeech() {} public void onRmsChanged(float v) {} public void onBufferReceived(byte[] b) {}
            public void onEndOfSpeech() {} public void onPartialResults(Bundle p) {} public void onEvent(int t, Bundle p) {}
        });
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        stt.startListening(i);
    }
    void heard(String t) { web.evaluateJavascript("window.__pedroHeard&&window.__pedroHeard(" + JSONObject.quote(t) + ")", null); }

    void postNotification(String title, String body) {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;
        Intent open = new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pi = PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder nb = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CH) : new Notification.Builder(this);
        nb.setSmallIcon(R.drawable.splash_icon).setContentTitle(title).setContentText(body)
          .setStyle(new Notification.BigTextStyle().bigText(body)).setAutoCancel(true).setContentIntent(pi);
        getSystemService(NotificationManager.class).notify((int) (System.currentTimeMillis() % 100000), nb.build());
    }

    @Override public void onRequestPermissionsResult(int code, String[] p, int[] g) {
        boolean ok = g.length > 0 && g[0] == PackageManager.PERMISSION_GRANTED;
        if (code == 1 && pendingWebPerm != null) { if (ok) pendingWebPerm.grant(pendingWebPerm.getResources()); else pendingWebPerm.deny(); pendingWebPerm = null; }
        if (code == 2) { if (ok) startListening(); else { toast("Mic permission is needed for voice"); heard(""); } }
    }
    @Override protected void onActivityResult(int req, int res, Intent data) {
        if (req == 9 && fileCb != null) { fileCb.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(res, data)); fileCb = null; }
    }
    @Override protected void onResume() { super.onResume(); resumed = true; web.onResume(); }
    @Override protected void onPause() { super.onPause(); resumed = false; web.onPause(); CookieManager.getInstance().flush(); }
    @Override protected void onStop() { super.onStop(); resumed = false; }

    @Override public void onBackPressed() {
        if (errorView.getVisibility() == View.VISIBLE) { errorView.setVisibility(View.GONE); return; }
        if (!showingAuth && !inPhone && web.canGoBack()) { web.goBack(); return; }
        new AlertDialog.Builder(this).setTitle("Ped Bot")
            .setItems(new String[]{"Sign out", "Reload", "Exit"}, (d, w) -> {
                if (w == 0) { prefs.edit().remove("ticket").remove("secret").remove("base").apply(); CookieManager.getInstance().removeAllCookies(null); showAuth(); }
                else if (w == 1) autoConnect();
                else finish();
            }).show();
    }

    int dp(int v) { return (int) (v * getResources().getDisplayMetrics().density); }
    /** 1.6.6: save a chat image/video/file to Downloads with the signed-in session (streamed by DownloadManager). */
    void saveToDownloads(String url, String disposition, String mime) {
        try {
            if (url == null || !(url.startsWith("http://") || url.startsWith("https://"))) { toast("Can't save this file from here."); return; }
            if (url.contains("phone.pedbot.local")) { toast("This file is on your PC - open it when your PC is online."); return; }
            String name = URLUtil.guessFileName(url, disposition, mime);
            try {
                String q = Uri.parse(url).getQueryParameter("path");
                if (q != null && !q.isEmpty()) { String n = q.replace('\\', '/'); n = n.substring(n.lastIndexOf('/') + 1); if (!n.isEmpty()) name = n; }
            } catch (Exception ignored) {}
            DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) r.addRequestHeader("Cookie", cookie);
            try {
                String access = new JSONObject(prefs.getString("ticket", "{}")).optString("access_token", "");
                if (!access.isEmpty()) r.addRequestHeader("Authorization", "Bearer " + access);
            } catch (Exception ignored) {}
            if (mime != null && !mime.isEmpty()) r.setMimeType(mime);
            r.setTitle(name);
            r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
            DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
            final long id = dm.enqueue(r);
            toast("Saving " + name + "…");
            final String shown = name;
            BroadcastReceiver done = new BroadcastReceiver() {
                @Override public void onReceive(Context c, Intent i) {
                    if (i.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1) != id) return;
                    try { unregisterReceiver(this); } catch (Exception ignored) {}
                    DownloadManager.Query q = new DownloadManager.Query().setFilterById(id);
                    try (android.database.Cursor cur = dm.query(q)) {
                        boolean ok = cur != null && cur.moveToFirst() && cur.getInt(cur.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS)) == DownloadManager.STATUS_SUCCESSFUL;
                        toast(ok ? "Saved to Downloads: " + shown : "Download failed - is your PC online?");
                    } catch (Exception e) { toast("Saved to Downloads"); }
                }
            };
            IntentFilter f = new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE);
            if (Build.VERSION.SDK_INT >= 33) registerReceiver(done, f, Context.RECEIVER_EXPORTED); else registerReceiver(done, f);
        } catch (Exception e) {
            toast("Couldn't save: " + e.getMessage());
        }
    }

    void toast(String s) { runOnUiThread(() -> Toast.makeText(this, s, Toast.LENGTH_SHORT).show()); }
    TextView text(String s, int sp, String c) { TextView t = new TextView(this); t.setText(s); t.setTextSize(sp); t.setTextColor(Color.parseColor(c)); t.setPadding(0, dp(10), 0, dp(6)); return t; }
    Button grokBtn(String s, boolean primary) {
        Button b = new Button(this); b.setText(s); b.setAllCaps(false);
        b.setTextColor(Color.parseColor(primary ? "#ffffff" : "#1d9bf0"));
        if (primary) b.setBackgroundColor(Color.parseColor("#1d9bf0"));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2); lp.topMargin = dp(8); b.setLayoutParams(lp);
        return b;
    }
}
