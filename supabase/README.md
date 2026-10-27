# Ped Bot sign-in (Supabase)

User accounts live in your Supabase project. Ped Bot never stores emails or
subscription rows in localStorage or in the app source. The browser only keeps
a session ticket (JWT) so you stay signed in.

## 1. Create a project

1. Open https://supabase.com/dashboard and create a project.
2. Wait until the database is ready.

## 2. Create the profiles table

1. Dashboard → **SQL Editor** → New query.
2. Paste `schema.sql` from this folder and Run.
3. Confirm Table Editor shows `public.profiles`.

## 3. Auth settings

Dashboard → **Authentication** → **URL Configuration**:

- Site URL: `http://127.0.0.1:8765`
- Redirect URLs: add `http://127.0.0.1:8765/` and `http://localhost:8765/`

Dashboard → **Authentication** → **Providers** → **Email**:

- Enable Email.
- For this desktop app, turn **Confirm email** off so the first sign-up can
  enter the app immediately. If you leave confirm on, the app will tell the
  user to check their inbox.

Optional Google / GitHub:

- Enable the provider and paste the client id/secret from Google or GitHub.
- Set `SUPABASE_OAUTH_GOOGLE=1` and/or `SUPABASE_OAUTH_GITHUB=1` in `.env`.

## 4. Keys in `.env`

Dashboard → **Project Settings** → **API**. Copy into
`C:\Users\POLASTOWER\AppData\Local\PedroAgent\.env`:

```
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
ADMIN_EMAIL=you@example.com
SUPABASE_OAUTH_GOOGLE=0
SUPABASE_OAUTH_GITHUB=0
```

`SUPABASE_ANON_KEY` is the public key (safe in the desktop UI).
`SUPABASE_SERVICE_ROLE_KEY` stays on this PC only. Never commit it or paste it
into chat.

`ADMIN_EMAIL` is the account that can open **Users** in the account menu.

Then **Quit Ped Bot from the tray** and start it again so `.env` reloads.

## 5. First admin

Sign up with the same address as `ADMIN_EMAIL`. That user can open **Users**.

To promote someone later in SQL:

```sql
update public.profiles
set role = 'admin'
where lower(email) = 'you@example.com';
```

## 6. See every signup

**In the app:** sign in as admin → account avatar → **Users**.
Shows email, name, signup date, subscription, and the total count.

**In Supabase:** Table Editor → `profiles`. Or SQL:

```sql
select count(*) as signups from public.profiles;
select email, full_name, created_at, subscription_status
from public.profiles
order by created_at desc;
```

## 7. Phone app (skip the Cloudflare paste)

After this schema is applied, Ped Bot writes the current tunnel URL to
`public.pc_presence` (service role only; the remote token is never stored).
The Android app signs in with the same email and password, reads that URL,
and opens the same Grok UI as the PC window.

Confirm email should stay off so the first phone sign-up can enter immediately.

## 8. Stripe later

Columns are already there: `subscription_status`, `stripe_customer_id`,
`stripe_subscription_id`, `plan`. New users are `free` with a null customer id.

Next steps when you add a paywall:

1. Create a Stripe customer on first checkout; save `stripe_customer_id`.
2. On webhook `checkout.session.completed` / `customer.subscription.updated`,
   set `subscription_status` to `trial` or `paid` and store `stripe_subscription_id`.
3. On `customer.subscription.deleted`, set `subscription_status` back to `free`.
4. Gate paid features by reading `profiles.subscription_status` in Ped (same
   JWT already sent as `Authorization: Bearer`).

## Phone-only mode (1.5.12)

Run `phone_sync.sql` once (SQL editor -> New query -> paste -> Run). It adds `pb_bots` and
`pb_messages`, both with row-level security so each account only sees its own rows. The PC syncs
with the service role for the account in `PEDBOT_OWNER_EMAIL` (or `ADMIN_EMAIL`). The phone signs in
with the same account and reads/writes with its own JWT. Gemini keys are never stored in Supabase.
