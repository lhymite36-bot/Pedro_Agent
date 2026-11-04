# Changelog

## 1.9.4-test - No more sign-out on a slow connection

- Fix: on a slow or flaky connection the app sent you back to the sign-in page. Root cause: the PC checked your sign-in with Supabase on every request (12 s limit, no retry). Any timeout, offline moment or Supabase 5xx was answered as "Please sign in" (401). The window then deleted the saved session and showed the sign-in screen.
- Now only a definite answer signs you out: Supabase rejecting the refresh token (or a 401 that a token refresh can't fix), or you tapping Log out. Timeouts, offline and 5xx keep the session.
- The PC remembers a sign-in it already checked. If Supabase is unreachable it keeps working (up to 7 days on the PC itself). Checks have longer timeouts (25 s) and a retry.
- A small "Slow connection, retrying…" / "You are offline" banner shows while Ped Bot retries (2, 4, 8, 15, 30 s). The screens reload by themselves when the connection is back.
- Phone: the password-on-open rule stays. A slow network during unlock now says "Slow connection, retrying…" and retries by itself instead of failing. An expired sign-in opens the password screen for your account, never sign up. Longer network timeouts (20 s connect / 30 s read).
- Pro stays Pro on a slow network: the plan is read from this PC, and a failed "Restore purchase" check never downgrades it.

## 1.9.3-test - Projects fixed, plus a polish pass

- Fix: opening a project no longer shows a blank page. A new project now shows a project card with its name, goal, team and quick buttons (Edit project, Plan the next steps, What's the status?).
- Fix: creating a project works on Free (1 project included) and Pro (unlimited). Free gets a clear message and the upgrade page for a 2nd project instead of a silent failure.
- New: Projects page on phone and PC, with the list, "+ New project", Edit, and an empty state. PC Projects used to scroll a hidden sidebar.
- Fix: Studio App factory waited 0 seconds and said "done, 0 files". It now follows the real build, shows live steps, and gives an "Open app" link served from /builds/<name>/ (safe: only files inside that build).
- Fix: Gemini 503 / busy. The whole turn retries after 3, 8 and 15 s, and any partial text from the failed try is cleared, so you never see "PONG" and then "busy".
- Fix: the female 3D avatar loads reliably. Clicks while loading are queued, there is a "still loading" note, a Retry / other-avatar fallback, and the other model preloads.
- Fix (phone): the Ped Bot face no longer overlaps the Connectors search box. The Connectors and Routines pages are full-screen and opaque.
- Fix (phone): the Live PC screen gets its own full-screen layout. Its controls no longer collide with the app header and bottom bar.
- Fix (PC): Model, Chat history and Memory in the menu did nothing. They now open the model picker, history and memory.
- Fix: Usage shows readable rows instead of raw JSON. Users shows a friendly note instead of a raw red error.
- Polish: one "Answered by <model>" chip per reply instead of a "switched to" chip for every model switch.

## 1.9.2-test - Pro fixes from the full test pass

- Fix: the upgrade page no longer pops up by itself on Free when the app starts or when you open any menu item. Studio's background call check used to trigger it.
- Fix: duplicating a bot from the More menu no longer gets around the 2-bot Free limit. The limit now applies to every way a bot is made.
- Tests: the groups picture test now uses the current avatar shapes. The older suites run as Pro (`tests/conftest.py`). New tests cover the bot and automation limits.

## 1.9.1-test - Ped Bot Pro (freemium, Razorpay TEST mode)

- **Bring your own key stays.** All AI still runs on your own Gemini key, on Free and Pro.
- **Free:** core chat, 2 bots, 1 automation, themes Grok Dark / Grok Light / Aurora.
- **Pro (Rs 199/month or Rs 1,499/year):** unlimited bots and automations, 3D avatars (male + female), all themes + custom colours, group chats, YouTube autopilot, Studio, Lab, Pro tools (Batch 2).
- New **Upgrade to Pro** page (PC account menu + phone apps grid), lock icons on Pro features, **Restore purchase**.
- Razorpay Checkout in **test mode only** (`RAZORPAY_KEY_ID=rzp_test_...` in `.env`; live keys refused). Optional `RAZORPAY_KEY_SECRET` on the PC creates orders and checks signatures. Dev **Simulate purchase** button (`PEDBOT_DEV_SIMULATE=0` hides it).
- Entitlement saved locally and, when signed in, in Supabase `pb_entitlements` (anon key + your JWT, RLS: own row only). Run `supabase/entitlements.sql` once. `supabase/functions/razorpay-verify` is a template for live payments (not deployed).
- Existing bots, groups and routines keep working; only new ones are limited on Free. The 1.9.0 "Pro" page is renamed **Pro tools**.

## 1.9.0-test (Batch 2)

- Phone control: Android AccessibilityService with Allow/Stop bubble, red STOP, banking/password/payment block.
- PC autopilot: screenshot → Gemini vision → click/type; step Allow by default; Ctrl+Shift+Esc+P / corner stop; logs in Documents\Ped Bot Logs.
- Long-term memory: per-bot local vector store, top 5 facts in replies, Memory page with edit/delete/export.
- Team tasks: planner / workers / checker, max 3 retries, live progress board, who-did-what.
- Real voice clone (PC): Piper or XTTS if installed, Lab › My voice consent required, else closest Gemini voice.
- Live video avatar: OBS Virtual Camera + optional VB-Cable, Speak for me / Q&A approve, always-on “AI assistant” label.
- Self-coding skills: sandbox test, Approve to go live, Disable and Undo, no system folders or secrets.
- Hey Ped + smart home: music links, volume/lock/apps/timers, optional local Home Assistant, phone listener pauses below 20% battery.
- Income bots: public job boards + RSS, draft proposals (you send them), local earnings tracker.
- Pro page on PC menu and phone apps grid. Risky tools default OFF in Settings › Advanced.
