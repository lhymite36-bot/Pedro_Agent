-- 1.9.1 Ped Bot Pro entitlements (one row per account). Run once in the Supabase SQL editor.
-- The app reads/writes with the anon key + the signed-in user's JWT. RLS limits every user to their own row.
-- Test/simulated rows may be written by the user (test build only). 'live' rows can only be written by a
-- server-side Edge Function holding the service role key (see supabase/functions/razorpay-verify) - never the app.
create table if not exists public.pb_entitlements (
  user_id uuid primary key references auth.users (id) on delete cascade,
  plan text not null default 'free' check (plan in ('free', 'pro')),
  period text check (period in ('month', 'year')),
  source text not null default 'test' check (source in ('test', 'simulated', 'live')),
  mode text not null default 'test' check (mode in ('test', 'live')),
  payment_id text,
  valid_until timestamptz,
  updated_at timestamptz not null default now()
);
alter table public.pb_entitlements enable row level security;

drop policy if exists "pb_ent_select_own" on public.pb_entitlements;
create policy "pb_ent_select_own" on public.pb_entitlements for select to authenticated
  using (auth.uid() = user_id);

drop policy if exists "pb_ent_insert_own_test" on public.pb_entitlements;
create policy "pb_ent_insert_own_test" on public.pb_entitlements for insert to authenticated
  with check (auth.uid() = user_id and mode = 'test' and source in ('test', 'simulated'));

drop policy if exists "pb_ent_update_own_test" on public.pb_entitlements;
create policy "pb_ent_update_own_test" on public.pb_entitlements for update to authenticated
  using (auth.uid() = user_id and mode = 'test')
  with check (auth.uid() = user_id and mode = 'test' and source in ('test', 'simulated'));
-- No delete policy: users cannot delete rows.
