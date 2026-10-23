-- Ped Bot profiles (Supabase / Postgres)
-- Run this once in the Supabase SQL editor:
--   Dashboard → SQL → New query → paste this file → Run
--
-- Auth users live in auth.users (managed by Supabase).
-- This table is the app profile: subscription, Stripe, admin role.
-- New signups get subscription_status = 'free' and stripe_customer_id = null.

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  email text not null unique,
  full_name text,
  created_at timestamptz not null default now(),
  last_login timestamptz,
  updated_at timestamptz not null default now(),
  subscription_status text not null default 'free'
    check (subscription_status in ('free', 'trial', 'paid')),
  stripe_customer_id text,
  stripe_subscription_id text,
  plan text,
  role text not null default 'user'
    check (role in ('user', 'admin'))
);

create index if not exists profiles_created_at_idx on public.profiles (created_at desc);
create index if not exists profiles_subscription_idx on public.profiles (subscription_status);
create index if not exists profiles_stripe_customer_idx on public.profiles (stripe_customer_id);

comment on table public.profiles is 'Ped Bot user profiles. One row per auth user. Ready for Stripe.';
comment on column public.profiles.subscription_status is 'free | trial | paid. New users are free.';
comment on column public.profiles.stripe_customer_id is 'Set when the user is created in Stripe. Null until paywall.';
comment on column public.profiles.stripe_subscription_id is 'Active Stripe subscription id, if any.';
comment on column public.profiles.role is 'user or admin. Promote with: update public.profiles set role = ''admin'' where lower(email) = ''you@example.com'';';

create or replace function public.set_profiles_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
before update on public.profiles
for each row execute procedure public.set_profiles_updated_at();

-- Create a profile row the moment someone signs up.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, full_name, subscription_status, role)
  values (
    new.id,
    new.email,
    nullif(trim(coalesce(
      new.raw_user_meta_data->>'full_name',
      new.raw_user_meta_data->>'name',
      ''
    )), ''),
    'free',
    'user'
  )
  on conflict (id) do update
    set email = excluded.email,
        full_name = coalesce(public.profiles.full_name, excluded.full_name);
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute procedure public.handle_new_user();

-- RLS: each user can read/update their own name. Billing and role stay server-only.
alter table public.profiles enable row level security;

create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select coalesce((
    select p.role = 'admin' from public.profiles p where p.id = auth.uid()
  ), false);
$$;

revoke all on public.profiles from anon, authenticated;
grant select, insert on public.profiles to authenticated;
grant update (full_name, last_login, updated_at) on public.profiles to authenticated;
grant all on public.profiles to postgres, service_role;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
  on public.profiles for select
  to authenticated
  using (id = auth.uid() or public.is_admin());

drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own"
  on public.profiles for insert
  to authenticated
  with check (id = auth.uid());

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
  on public.profiles for update
  to authenticated
  using (id = auth.uid())
  with check (id = auth.uid());

-- Phone app finds this PC after email sign-in. Ped upserts the tunnel URL
-- with the service role (never the remote token). Signed-in users may read it.
create table if not exists public.pc_presence (
  id text primary key default 'default',
  url text not null,
  updated_at timestamptz not null default now()
);

comment on table public.pc_presence is 'Current Cloudflare URL for this Ped Bot PC. No tokens.';

alter table public.pc_presence enable row level security;

revoke all on public.pc_presence from anon, authenticated;
grant select on public.pc_presence to authenticated;
grant all on public.pc_presence to postgres, service_role;

drop policy if exists "pc_presence_select_auth" on public.pc_presence;
create policy "pc_presence_select_auth"
  on public.pc_presence for select
  to authenticated
  using (true);
