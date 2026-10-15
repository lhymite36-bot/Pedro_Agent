package com.pedro.agent;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.*;
import android.speech.*;
import android.text.InputType;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import java.util.ArrayList;

public class MainActivity extends Activity {
    static final String PREFS = "pedro", CH = "pedro_replies";
    WebView web; LinearLayout setup, errorView; TextView errText;
    SharedPreferences prefs; PermissionRequest pendingWebPerm; ValueCallback<Uri[]> fileCb;
    SpeechRecognizer stt; boolean resumed;

    @Override protected void onCreate(Bundle b) {
        setTheme(android.R.style.Theme_Material_NoActionBar);
        super.onCreate(b);
        getWindow().setStatusBarColor(Color.parseColor("#0B0B0F"));
        getWindow().setNavigationBarColor(Color.parseColor("#0B0B0F"));
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel c = new NotificationChannel(CH, "Agent replies", NotificationManager.IMPORTANCE_DEFAULT);
            getSystemService(NotificationManager.class).createNotificationChannel(c);
        }
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#0B0B0F"));
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        setup = buildSetup(); root.addView(setup, new FrameLayout.LayoutParams(-1, -1));
        errorView = buildError(); root.addView(errorView, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);
        configureWeb();
        String shared = getIntent() != null ? getIntent().getStringExtra(Intent.EXTRA_TEXT) : null;
        if (shared != null && shared.contains("http")) { prefillSetup(shared); showSetup(); }
        else if (prefs.getString("base", "").isEmpty()) showSetup();
        else autoConnect(true);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 3);
    }

    @Override protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        String s = i.getStringExtra(Intent.EXTRA_TEXT);
        if (s != null && s.contains("http")) { prefillSetup(s); showSetup(); }
    }

    // ---------- setup screen ----------
    EditText linkIn, secretIn;
    LinearLayout buildSetup() {
        LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.VERTICAL);
        l.setBackgroundColor(Color.parseColor("#0B0B0F")); int p = dp(24); l.setPadding(p, dp(56), p, p);
        ImageView logo = new ImageView(this); logo.setImageResource(R.drawable.splash_icon);
        l.addView(logo, new LinearLayout.LayoutParams(dp(96), dp(96)));
        l.addView(text("Pedro Agent", 26, "#ECECF1"));
        l.addView(text("On your PC open Pedro Agent › Settings › Connect phone, then scan the QR code.", 14, "#8E8EA0"));
        Button scan = button("Scan QR"); scan.setOnClickListener(v -> startScan()); l.addView(scan);
        l.addView(text("No camera? Type the link and the pairing code (or your token) shown on the PC:", 14, "#8E8EA0"));
        linkIn = input("https://xxxx.trycloudflare.com/login#t=…", false); l.addView(linkIn);
        secretIn = input("Pairing code (ABCD-1234), token or PIN", true); l.addView(secretIn);
        Button paste = button("Paste from clipboard"); paste.setOnClickListener(v -> {
            ClipboardManager cm = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
            if (cm.hasPrimaryClip() && cm.getPrimaryClip().getItemCount() > 0) {
                CharSequence t = cm.getPrimaryClip().getItemAt(0).coerceToText(this); if (t != null) prefillSetup(t.toString()); }
        }); l.addView(paste);
        Button go = button("Connect"); go.setOnClickListener(v -> saveAndConnect()); l.addView(go);
        Button cancel = button("Cancel"); cancel.setOnClickListener(v -> { if (!prefs.getString("base", "").isEmpty()) { setup.setVisibility(View.GONE); } }); l.addView(cancel);
        ScrollView sv = new ScrollView(this); sv.addView(l);
        LinearLayout wrap = new LinearLayout(this); wrap.addView(sv, new LinearLayout.LayoutParams(-1, -1)); return wrap;
    }

    void prefillSetup(String raw) {
        raw = raw.trim(); int i = raw.indexOf("http"); if (i > 0) raw = raw.substring(i);
        int sp = raw.indexOf(' '); if (sp > 0) raw = raw.substring(0, sp);
        linkIn.setText(raw);
        String t = tokenFrom(raw); if (!t.isEmpty()) secretIn.setText(t);
    }

    static String tokenFrom(String raw) {
        int h = raw.indexOf('#'); if (h < 0) return "";
        for (String kv : raw.substring(h + 1).split("&")) if (kv.startsWith("t=")) return Uri.decode(kv.substring(2));
        return "";
    }
    static String baseFrom(String raw) {
        Uri u = Uri.parse(raw.trim()); if (u.getScheme() == null || u.getHost() == null) return "";
        String s = u.getScheme() + "://" + u.getHost(); if (u.getPort() > 0) s += ":" + u.getPort(); return s;
    }

    void saveAndConnect() {
        String raw = linkIn.getText().toString().trim();
        if (!raw.startsWith("http")) raw = "https://" + raw;
        String base = baseFrom(raw), secret = secretIn.getText().toString().trim();
        if (secret.isEmpty()) secret = tokenFrom(raw);
        if (base.isEmpty()) { toast("That link doesn't look right"); return; }
        if (secret.toUpperCase().replace(" ", "").matches("[A-Z0-9]{4}-?[A-Z0-9]{4}")) { pairWith(base, secret); return; }
        if (secret.isEmpty() && prefs.getString("secret", "").isEmpty()) { toast("Add your token or PIN"); return; }
        SharedPreferences.Editor e = prefs.edit().putString("base", base);
        if (!secret.isEmpty()) e.putString("secret", secret);
        e.apply();
        CookieManager.getInstance().removeAllCookies(null);
        openServer(true);
    }

    void showSetup() {
        if (linkIn.getText().length() == 0) linkIn.setText(prefs.getString("base", ""));
        setup.setVisibility(View.VISIBLE); errorView.setVisibility(View.GONE);
    }

    // ---------- error screen ----------
    LinearLayout buildError() {
        LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.VERTICAL); l.setGravity(Gravity.CENTER);
        l.setBackgroundColor(Color.parseColor("#0B0B0F")); int p = dp(24); l.setPadding(p, p, p, p);
        ImageView logo = new ImageView(this); logo.setImageResource(R.drawable.splash_icon);
        l.addView(logo, new LinearLayout.LayoutParams(dp(96), dp(96)));
        errText = text("Can't reach your PC.", 16, "#ECECF1"); errText.setGravity(Gravity.CENTER); l.addView(errText);
        TextView hint = text("Is Pedro Agent running on your PC? The link changes each time it starts. Check Telegram for the new one.", 14, "#8E8EA0");
        hint.setGravity(Gravity.CENTER); l.addView(hint);
        Button retry = button("Try again"); retry.setOnClickListener(v -> autoConnect(true)); l.addView(retry);
        Button newLink = button("Paste new link"); newLink.setOnClickListener(v -> { linkIn.setText(""); secretIn.setText(""); showSetup(); }); l.addView(newLink);
        l.setVisibility(View.GONE); return l;
    }

    // ---------- web ----------
    void configureWeb() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true); s.setDomStorageEnabled(true); s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false); s.setAllowFileAccess(false);
        s.setUserAgentString(s.getUserAgentString() + " PedroAgentApp/1.3");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setBackgroundColor(Color.parseColor("#0B0B0F"));
        web.addJavascriptInterface(new Bridge(), "PedroNative");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl(); String base = prefs.getString("base", "");
                if (!base.isEmpty() && u.toString().startsWith(base)) return false;
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) {}
                return true;
            }
            @Override public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) failOrRefresh("Can't reach your PC (" + e.getDescription() + ").");
            }
            @Override public void onReceivedHttpError(WebView v, WebResourceRequest r, WebResourceResponse resp) {
                if (r.isForMainFrame() && (resp.getStatusCode() == 530 || resp.getStatusCode() == 502 || resp.getStatusCode() == 404 && r.getUrl().getHost().endsWith("trycloudflare.com")))
                    failOrRefresh("That link has expired (" + resp.getStatusCode() + "). Paste the new one from Telegram.");
            }
            @Override public void onPageFinished(WebView v, String url) {
                CookieManager.getInstance().flush(); refreshedThisTry = false;
                v.evaluateJavascript(INJECT, null);
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest req) {
                runOnUiThread(() -> {
                    boolean cam = java.util.Arrays.asList(req.getResources()).contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE);
                    String perm = cam ? Manifest.permission.CAMERA : Manifest.permission.RECORD_AUDIO;
                    if (cam && !web.getUrl().startsWith("file:///android_asset/")) { req.deny(); return; }
                    if (checkSelfPermission(perm) == PackageManager.PERMISSION_GRANTED) req.grant(req.getResources());
                    else { pendingWebPerm = req; requestPermissions(new String[]{perm}, 1); }
                });
            }
            @Override public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (fileCb != null) fileCb.onReceiveValue(null); fileCb = cb;
                try { startActivityForResult(chooserIntent(p), 9); } catch (Exception e) { fileCb = null; return false; }
                return true;
            }
        });
    }

    void openServer(boolean viaLogin) {
        String base = prefs.getString("base", ""), secret = prefs.getString("secret", "");
        if (base.isEmpty()) { showSetup(); return; }
        setup.setVisibility(View.GONE); errorView.setVisibility(View.GONE);
        // Sign in through the server's own /login page; the secret rides in the #fragment, never in logs.
        web.loadUrl(viaLogin && !secret.isEmpty() ? base + "/login#t=" + Uri.encode(secret) : base + "/");
    }

    // ---------- QR pairing ----------
    void startScan() {
        setup.setVisibility(View.GONE); errorView.setVisibility(View.GONE);
        web.loadUrl("file:///android_asset/scan.html");
    }

    void handlePairUri(String data) {
        Uri u = Uri.parse(data == null ? "" : data.trim());
        if (!"pedroagent".equals(u.getScheme()) || !"pair".equals(u.getHost())) { toast("That isn't a Pedro Agent QR code"); showSetup(); return; }
        String base = baseFrom(u.getQueryParameter("u") == null ? "" : u.getQueryParameter("u")), code = u.getQueryParameter("c");
        if (base.isEmpty() || !base.startsWith("https://") || code == null) { toast("That QR code is incomplete"); showSetup(); return; }
        linkIn.setText(base); pairWith(base, code);
    }

    /** Exchange a one-time pairing code for the access token, then connect. */
    void pairWith(String base, String code) {
        toast("Pairing with your PC…");
        new Thread(() -> {
            String token = "", err = "Pairing failed";
            try {
                java.net.HttpURLConnection c = (java.net.HttpURLConnection) new java.net.URL(base + "/pair").openConnection();
                c.setConnectTimeout(10000); c.setReadTimeout(10000); c.setRequestMethod("POST"); c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                c.getOutputStream().write(new org.json.JSONObject().put("code", code.trim().toUpperCase()).toString().getBytes("UTF-8"));
                java.io.InputStream in = c.getResponseCode() < 400 ? c.getInputStream() : c.getErrorStream();
                java.util.Scanner sc = new java.util.Scanner(in, "UTF-8").useDelimiter("\\A");
                org.json.JSONObject r = new org.json.JSONObject(sc.hasNext() ? sc.next() : "{}");
                token = r.optString("token", ""); err = r.optString("error", err);
            } catch (Exception e) { err = "Can't reach your PC: " + e.getMessage(); }
            final String t = token, e2 = err;
            runOnUiThread(() -> {
                if (t.isEmpty()) { toast(e2); showSetup(); return; }
                prefs.edit().putString("base", base).putString("secret", t).apply();
                CookieManager.getInstance().removeAllCookies(null); toast("Paired! Connecting…"); openServer(true);
            });
        }).start();
    }

    // ---------- auto-connect: read the PC's signed current link ----------
    static final String NTFY = "https://ntfy.sh/";
    boolean refreshedThisTry;

    static String hex(byte[] b) { StringBuilder sb = new StringBuilder(); for (byte x : b) sb.append(String.format("%02x", x)); return sb.toString(); }

    /** Latest verified URL published by the PC, or "" (network/no message/bad signature). */
    static String fetchPublished(String token) {
        if (token == null || token.length() < 16) return "";
        try {
            String topic = "pedro-" + hex(java.security.MessageDigest.getInstance("SHA-256").digest(("pedro-topic:" + token).getBytes("UTF-8"))).substring(0, 32);
            java.net.HttpURLConnection c = (java.net.HttpURLConnection) new java.net.URL(NTFY + topic + "/json?poll=1&since=all").openConnection();
            c.setConnectTimeout(6000); c.setReadTimeout(6000);
            java.io.BufferedReader in = new java.io.BufferedReader(new java.io.InputStreamReader(c.getInputStream(), "UTF-8"));
            String line, best = ""; long bestTs = -1;
            javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
            mac.init(new javax.crypto.spec.SecretKeySpec(("pedro-url:" + token).getBytes("UTF-8"), "HmacSHA256"));
            while ((line = in.readLine()) != null) {
                try {
                    org.json.JSONObject ev = new org.json.JSONObject(line);
                    if (!"message".equals(ev.optString("event"))) continue;
                    org.json.JSONObject d = new org.json.JSONObject(ev.optString("message"));
                    String url = d.getString("url"); long ts = d.getLong("ts");
                    String sig = hex(mac.doFinal((url + "|" + ts).getBytes("UTF-8")));
                    if (url.startsWith("https://") && java.security.MessageDigest.isEqual(sig.getBytes(), d.getString("sig").getBytes()) && ts > bestTs) { best = url; bestTs = ts; }
                } catch (Exception ignored) {}
            }
            in.close(); return best;
        } catch (Exception e) { return ""; }
    }

    /** Check the published link first; fall back to the saved one. */
    void autoConnect(boolean viaLogin) {
        refreshedThisTry = true;
        String secret = prefs.getString("secret", "");
        if (secret.isEmpty() && prefs.getString("base", "").isEmpty()) { showSetup(); return; }
        new Thread(() -> {
            String url = fetchPublished(secret);
            runOnUiThread(() -> {
                if (!url.isEmpty() && !url.equals(prefs.getString("base", ""))) {
                    prefs.edit().putString("base", url).apply(); CookieManager.getInstance().removeAllCookies(null); toast("Connected to your PC's new link");
                }
                openServer(viaLogin);
            });
        }).start();
    }

    /** On a dead link: try the published link once, then show the error screen. */
    void failOrRefresh(String msg) {
        if (refreshedThisTry) { refreshedThisTry = false; showError(msg); return; }
        String old = prefs.getString("base", ""), secret = prefs.getString("secret", "");
        new Thread(() -> {
            String url = fetchPublished(secret);
            runOnUiThread(() -> {
                if (!url.isEmpty() && !url.equals(old)) { prefs.edit().putString("base", url).apply(); CookieManager.getInstance().removeAllCookies(null); refreshedThisTry = true; openServer(true); }
                else showError(msg);
            });
        }).start();
    }

    void showError(String msg) { runOnUiThread(() -> { errText.setText(msg); errorView.setVisibility(View.VISIBLE); }); }

    // Hooks the page's mic button to the phone's own speech recognition, and mirrors new replies to notifications.
    static final String INJECT = "(function(){if(window.__pedroApp)return;window.__pedroApp=1;"
        + "var of=window.fetch,lastRe=0;window.fetch=function(u,o){return of.apply(this,arguments).then(function(r){var ct=(r.headers.get('content-type')||'');"
        + "var api=String(u&&u.url||u).indexOf('/api')>=0||(o&&o.method&&o.method!='GET');"
        + "if(api&&(r.status==401||r.status>=500&&ct.indexOf('json')<0||ct.indexOf('text/html')>=0)){if(Date.now()-lastRe>15000){lastRe=Date.now();PedroNative.reauth();}"
        + "throw new Error('Reconnecting to your PC, try again in a few seconds');}return r;});};"
        + "if(location.pathname==='/login'){var f=document.querySelector('form');if(f&&!document.getElementById('pa-x')){var a=document.createElement('a');a.id='pa-x';a.textContent='Use a different link';a.href='#';a.style.cssText='display:block;margin-top:16px;color:#7c8cff';a.onclick=function(e){e.preventDefault();PedroNative.newLink()};f.after(a)}return;}"
        + "document.addEventListener('click',function(e){var m=e.target.closest&&e.target.closest('#mic');if(!m)return;e.preventDefault();e.stopImmediatePropagation();m.classList.add('on');PedroNative.listen();},true);"
        + "window.__pedroHeard=function(t){var b=document.getElementById('mic');if(b)b.classList.remove('on');if(!t)return;var x=document.getElementById('t');if(!x)return;x.value=t;x.dispatchEvent(new Event('input',{bubbles:true}));var s=document.getElementById('send');if(s)s.click();};"
        + "var seen=0;function cnt(){return document.querySelectorAll('.msg.bot,.msg.assistant,[data-role=assistant]').length}seen=cnt();"
        + "new MutationObserver(function(){var n=cnt();if(n>seen){seen=n;if(document.hidden){var els=document.querySelectorAll('.msg.bot,.msg.assistant,[data-role=assistant]');var el=els[els.length-1];setTimeout(function(){PedroNative.notify('Pedro Agent',(el.innerText||'New reply').slice(0,300))},4000)}}}).observe(document.body,{childList:true,subtree:true});"
        + "})();";

    class Bridge {
        @JavascriptInterface public void scanned(String data) { runOnUiThread(() -> { if (web.getUrl() != null && web.getUrl().startsWith("file:///android_asset/scan.html")) handlePairUri(data); }); }
        @JavascriptInterface public void scanCancel() { runOnUiThread(() -> { if (web.getUrl() != null && web.getUrl().startsWith("file:///android_asset/")) { web.loadUrl("about:blank"); showSetup(); } }); }
        @JavascriptInterface public void reauth() { runOnUiThread(() -> { CookieManager.getInstance().removeAllCookies(null); toast("Reconnecting to your PC…"); autoConnect(true); }); }
        @JavascriptInterface public void listen() { runOnUiThread(MainActivity.this::startListening); }
        @JavascriptInterface public void newLink() { runOnUiThread(() -> { linkIn.setText(""); secretIn.setText(""); showSetup(); }); }
        @JavascriptInterface public void notify(String title, String body) { if (!resumed) postNotification(title, body); }
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
    void heard(String t) { web.evaluateJavascript("window.__pedroHeard&&window.__pedroHeard(" + org.json.JSONObject.quote(t) + ")", null); }

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
    // 1.3.1: the page asks for pictures AND documents, several at once. WebView's own createIntent()
    // only uses the first type (so PDFs were greyed out) and never allows multiple picks.
    Intent chooserIntent(WebChromeClient.FileChooserParams p) {
        Intent i = new Intent(Intent.ACTION_GET_CONTENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("*/*");
        ArrayList<String> mimes = new ArrayList<>();
        for (String a : p.getAcceptTypes()) {
            for (String t : a.split(",")) {
                t = t.trim().toLowerCase();
                if (t.isEmpty()) continue;
                if (t.startsWith(".")) { String m = MimeTypeMap.getSingleton().getMimeTypeFromExtension(t.substring(1)); if (m != null) t = m; else continue; }
                if (!mimes.contains(t)) mimes.add(t);
            }
        }
        if (!mimes.isEmpty()) i.putExtra(Intent.EXTRA_MIME_TYPES, mimes.toArray(new String[0]));
        if (p.getMode() == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE) i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        return Intent.createChooser(i, "Attach to Pedro Agent");
    }
    @Override protected void onActivityResult(int req, int res, Intent data) {
        if (req != 9 || fileCb == null) return;
        Uri[] out = null;
        if (res == RESULT_OK && data != null) {
            ClipData clip = data.getClipData();
            if (clip != null && clip.getItemCount() > 0) {
                out = new Uri[clip.getItemCount()];
                for (int k = 0; k < out.length; k++) out[k] = clip.getItemAt(k).getUri();
            } else if (data.getData() != null) out = new Uri[]{data.getData()};
        }
        fileCb.onReceiveValue(out); fileCb = null;
    }
    @Override protected void onResume() { super.onResume(); resumed = true; web.onResume(); }
    @Override protected void onPause() { super.onPause(); resumed = false; web.onPause(); CookieManager.getInstance().flush(); }
    @Override protected void onStop() { super.onStop(); resumed = false; }

    @Override public void onBackPressed() {
        if (setup.getVisibility() == View.VISIBLE && !prefs.getString("base", "").isEmpty()) { setup.setVisibility(View.GONE); return; }
        if (web.canGoBack() && errorView.getVisibility() != View.VISIBLE) { web.goBack(); return; }
        new AlertDialog.Builder(this).setTitle("Pedro Agent")
            .setItems(new String[]{"Paste new link", "Reload", "Exit"}, (d, w) -> {
                if (w == 0) { linkIn.setText(""); secretIn.setText(""); showSetup(); }
                else if (w == 1) openServer(true); else finish();
            }).show();
    }

    // ---------- helpers ----------
    int dp(int v) { return (int) (v * getResources().getDisplayMetrics().density); }
    void toast(String s) { runOnUiThread(() -> Toast.makeText(this, s, Toast.LENGTH_SHORT).show()); }
    TextView text(String s, int sp, String c) { TextView t = new TextView(this); t.setText(s); t.setTextSize(sp); t.setTextColor(Color.parseColor(c)); t.setPadding(0, dp(10), 0, dp(6)); return t; }
    EditText input(String hint, boolean secret) {
        EditText e = new EditText(this); e.setHint(hint); e.setTextColor(Color.WHITE); e.setHintTextColor(Color.parseColor("#6E6E80"));
        e.setSingleLine(true); e.setInputType(secret ? (InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD) : InputType.TYPE_TEXT_VARIATION_URI | InputType.TYPE_CLASS_TEXT); return e; }
    Button button(String s) { Button b = new Button(this); b.setText(s); b.setAllCaps(false); return b; }
}
