# Changelog

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
