package com.pedro.agent;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.List;
import java.util.Locale;

/** Taps and types on command, with Allow / Stop on every action and a red STOP at all times. */
public class PedAccessibilityService extends AccessibilityService {
    static volatile PedAccessibilityService inst;
    static volatile String lastTree = "{}";
    static volatile String pendingPreview = "";
    static volatile boolean waiting;
    static volatile boolean stopped;
    static volatile boolean sensitive;
    static volatile String sensitiveWhy = "";

    final Handler main = new Handler(Looper.getMainLooper());
    WindowManager wm;
    View stopBtn, bubble;
    JSONArray queue;
    int index;
    final Object gate = new Object();

    static final String[] PACKAGES = {
        "com.google.android.apps.nbu.paisa.user", "com.google.android.apps.walletnfcrel",
        "com.phonepe.app", "net.one97.paytm", "com.csam.icici.bank.imobile",
        "com.sbi.lotusintouch", "com.axis.mobile", "com.snapwork.hdfc",
        "com.msf.kbank.mobile", "com.bankofbaroda.mconnect"
    };
    static final String[] WORDS = {
        "password", "passcode", "upi pin", "enter pin", "cvv", "cvc", "otp",
        "one-time password", "card number", "expiry", "net banking",
        "confirm payment", "authorize payment", "pay now", "3-d secure", "3d secure"
    };

    @Override public void onServiceConnected() {
        inst = this;
        wm = (WindowManager) getSystemService(WINDOW_SERVICE);
        main.post(this::showStop);
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent e) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;
        try {
            JSONObject tree = dump(root, 0);
            String pkg = String.valueOf(e.getPackageName() == null ? tree.optString("package") : e.getPackageName());
            tree.put("package", pkg);
            lastTree = tree.toString();
            String why = sensitiveWhy(root, pkg);
            sensitive = why != null;
            sensitiveWhy = why == null ? "" : why;
        } catch (Exception ignored) {
        } finally {
            root.recycle();
        }
    }

    @Override public void onInterrupt() { stopRun(); }

    @Override public void onDestroy() {
        inst = null;
        hideOverlays();
        super.onDestroy();
    }

    public static String statusJson() {
        try {
            JSONObject o = new JSONObject();
            o.put("enabled", inst != null);
            o.put("sensitive", sensitive);
            o.put("reason", sensitiveWhy);
            o.put("pending", pendingPreview);
            o.put("waiting", waiting);
            o.put("stopped", stopped);
            return o.toString();
        } catch (Exception e) { return "{\"enabled\":false}"; }
    }

    public static String treeJson() { return lastTree == null ? "{}" : lastTree; }

    public void runSteps(String json) {
        stopped = false;
        try { queue = new JSONArray(json); } catch (Exception e) { queue = new JSONArray(); }
        index = 0;
        new Thread(this::loop, "ped-a11y").start();
    }

    public void allow() {
        synchronized (gate) { waiting = false; gate.notifyAll(); }
        main.post(this::hideBubble);
    }

    public void stopRun() {
        stopped = true;
        synchronized (gate) { waiting = false; gate.notifyAll(); }
        pendingPreview = "";
        main.post(this::hideBubble);
    }

    void loop() {
        if (queue == null) return;
        for (; index < queue.length() && !stopped; index++) {
            JSONObject step = queue.optJSONObject(index);
            if (step == null) continue;
            if (sensitive) { pendingPreview = sensitiveWhy; break; }
            String preview = step.optString("preview", step.optString("say", "Next action"));
            pendingPreview = preview;
            waiting = true;
            main.post(() -> showBubble(preview));
            synchronized (gate) {
                while (waiting && !stopped) {
                    try { gate.wait(200); } catch (InterruptedException ignored) {}
                }
            }
            if (stopped) break;
            if (sensitive) break;
            main.post(() -> perform(step));
            try { Thread.sleep(350); } catch (InterruptedException ignored) {}
        }
        pendingPreview = "";
        waiting = false;
        main.post(this::hideBubble);
    }

    void perform(JSONObject step) {
        String action = step.optString("action", "tap").toLowerCase(Locale.US);
        if ("back".equals(action)) { performGlobalAction(GLOBAL_ACTION_BACK); return; }
        if ("home".equals(action)) { performGlobalAction(GLOBAL_ACTION_HOME); return; }
        if ("wait".equals(action)) return;
        if ("open".equals(action)) { openApp(step.optString("app")); return; }
        if ("type".equals(action)) { typeIntoFocused(step.optString("text")); return; }
        if ("key".equals(action) && "enter".equals(step.optString("key").toLowerCase(Locale.US))) {
            tapNode(findByText("Search"));
            return;
        }
        AccessibilityNodeInfo n = findByText(step.optString("target", step.optString("app", "")));
        if (n != null) tapNode(n); else tapCenter();
    }

    void openApp(String name) {
        String pkg = packageFor(name);
        try {
            startActivity(getPackageManager().getLaunchIntentForPackage(pkg));
        } catch (Exception e) {
            AccessibilityNodeInfo n = findByText(name);
            if (n != null) tapNode(n);
        }
    }

    String packageFor(String name) {
        String n = (name == null ? "" : name).toLowerCase(Locale.US);
        if (n.contains("youtube")) return "com.google.android.youtube";
        if (n.contains("chrome")) return "com.android.chrome";
        if (n.contains("gmail")) return "com.google.android.gm";
        if (n.contains("maps")) return "com.google.android.apps.maps";
        if (n.contains("spotify")) return "com.spotify.music";
        if (n.contains("settings")) return "com.android.settings";
        return n;
    }

    AccessibilityNodeInfo findByText(String text) {
        if (text == null || text.isEmpty()) return null;
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return null;
        try {
            List<AccessibilityNodeInfo> found = root.findAccessibilityNodeInfosByText(text);
            if (found != null && !found.isEmpty()) return found.get(0);
            return walkFind(root, text.toLowerCase(Locale.US));
        } catch (Exception e) { return null; }
    }

    AccessibilityNodeInfo walkFind(AccessibilityNodeInfo n, String q) {
        if (n == null) return null;
        CharSequence t = n.getText(); CharSequence d = n.getContentDescription();
        String hay = ((t == null ? "" : t) + " " + (d == null ? "" : d)).toLowerCase(Locale.US);
        if (hay.contains(q) && n.isClickable()) return n;
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo c = n.getChild(i);
            AccessibilityNodeInfo hit = walkFind(c, q);
            if (hit != null) return hit;
        }
        return null;
    }

    void tapNode(AccessibilityNodeInfo n) {
        if (n == null) return;
        if (n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return;
        android.graphics.Rect r = new android.graphics.Rect();
        n.getBoundsInScreen(r);
        tap(r.centerX(), r.centerY());
    }

    void tapCenter() {
        int w = getResources().getDisplayMetrics().widthPixels;
        int h = getResources().getDisplayMetrics().heightPixels;
        tap(w / 2, h / 2);
    }

    void tap(int x, int y) {
        if (Build.VERSION.SDK_INT < 24) return;
        Path p = new Path(); p.moveTo(x, y);
        GestureDescription.StrokeDescription s = new GestureDescription.StrokeDescription(p, 0, 80);
        dispatchGesture(new GestureDescription.Builder().addStroke(s).build(), null, null);
    }

    void typeIntoFocused(String text) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return;
        AccessibilityNodeInfo focus = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if (focus == null) focus = walkEditable(root);
        if (focus == null) return;
        android.os.Bundle b = new android.os.Bundle();
        b.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        focus.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, b);
    }

    AccessibilityNodeInfo walkEditable(AccessibilityNodeInfo n) {
        if (n == null) return null;
        if (n.isEditable()) return n;
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo hit = walkEditable(n.getChild(i));
            if (hit != null) return hit;
        }
        return null;
    }

    String sensitiveWhy(AccessibilityNodeInfo root, String pkg) {
        String p = pkg == null ? "" : pkg.toLowerCase(Locale.US);
        for (String s : PACKAGES) if (p.equals(s)) return "This looks like a banking or payment app, so Ped Bot will not tap it.";
        if (p.contains("bank") || p.contains("upi")) return "Banking screens are blocked.";
        String blob = flatten(root, new StringBuilder(), 0).toString().toLowerCase(Locale.US);
        if (hasPassword(root)) return "A password field is focused. Ped Bot will not type here.";
        for (String w : WORDS) if (blob.contains(w)) return "This screen asks for a password, PIN or payment detail. Ped Bot will not type here.";
        return null;
    }

    boolean hasPassword(AccessibilityNodeInfo n) {
        if (n == null) return false;
        if (n.isPassword()) return true;
        for (int i = 0; i < n.getChildCount(); i++) if (hasPassword(n.getChild(i))) return true;
        return false;
    }

    StringBuilder flatten(AccessibilityNodeInfo n, StringBuilder sb, int depth) {
        if (n == null || depth > 12) return sb;
        if (n.getText() != null) sb.append(' ').append(n.getText());
        if (n.getContentDescription() != null) sb.append(' ').append(n.getContentDescription());
        for (int i = 0; i < n.getChildCount(); i++) flatten(n.getChild(i), sb, depth + 1);
        return sb;
    }

    JSONObject dump(AccessibilityNodeInfo n, int depth) throws Exception {
        JSONObject o = new JSONObject();
        if (n == null || depth > 8) return o;
        o.put("text", n.getText() == null ? "" : n.getText().toString());
        o.put("desc", n.getContentDescription() == null ? "" : n.getContentDescription().toString());
        o.put("id", n.getViewIdResourceName() == null ? "" : n.getViewIdResourceName());
        o.put("click", n.isClickable());
        o.put("password", n.isPassword());
        o.put("package", n.getPackageName() == null ? "" : n.getPackageName().toString());
        JSONArray kids = new JSONArray();
        if (depth < 5) {
            for (int i = 0; i < n.getChildCount() && i < 40; i++) {
                AccessibilityNodeInfo c = n.getChild(i);
                if (c != null) kids.put(dump(c, depth + 1));
            }
        }
        o.put("children", kids);
        return o;
    }

    void showStop() {
        if (stopBtn != null || wm == null) return;
        Button b = new Button(this);
        b.setText("STOP");
        b.setTextColor(0xFFFFFFFF);
        b.setBackgroundColor(0xFFE0245E);
        b.setOnClickListener(v -> stopRun());
        WindowManager.LayoutParams lp = overlayParams();
        lp.width = dp(72); lp.height = dp(72);
        lp.gravity = Gravity.BOTTOM | Gravity.END;
        lp.x = dp(12); lp.y = dp(96);
        stopBtn = b;
        try { wm.addView(b, lp); } catch (Exception ignored) { stopBtn = null; }
    }

    void showBubble(String preview) {
        hideBubble();
        if (wm == null) return;
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundColor(0xF016181C);
        int pad = dp(14); box.setPadding(pad, pad, pad, pad);
        TextView t = new TextView(this);
        t.setText(preview);
        t.setTextColor(0xFFF7F9F9);
        t.setTextSize(16);
        box.addView(t);
        LinearLayout row = new LinearLayout(this);
        Button stop = pill("Stop", 0xFFE0245E); stop.setOnClickListener(v -> stopRun());
        Button allow = pill("Allow", 0xFF1D6FE0); allow.setOnClickListener(v -> allow());
        row.addView(stop); row.addView(allow);
        box.addView(row);
        WindowManager.LayoutParams lp = overlayParams();
        lp.width = WindowManager.LayoutParams.MATCH_PARENT;
        lp.height = WindowManager.LayoutParams.WRAP_CONTENT;
        lp.gravity = Gravity.BOTTOM;
        lp.y = dp(180);
        bubble = box;
        try { wm.addView(box, lp); } catch (Exception ignored) { bubble = null; }
    }

    Button pill(String label, int bg) {
        Button b = new Button(this);
        b.setText(label); b.setTextColor(0xFFFFFFFF); b.setBackgroundColor(bg);
        return b;
    }

    void hideBubble() {
        if (bubble != null && wm != null) try { wm.removeView(bubble); } catch (Exception ignored) {}
        bubble = null;
    }

    void hideOverlays() {
        hideBubble();
        if (stopBtn != null && wm != null) try { wm.removeView(stopBtn); } catch (Exception ignored) {}
        stopBtn = null;
    }

    WindowManager.LayoutParams overlayParams() {
        int type = Build.VERSION.SDK_INT >= 22
            ? WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY
            : WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY;
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT);
        return lp;
    }

    int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }
}
