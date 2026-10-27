-- Ped Bot phone-only mode (1.5.12): bots and chat messages synced between PC and phone.
-- Run once in Supabase: Dashboard -> SQL -> New query -> paste this file -> Run.
-- Every row belongs to one user (user_id = auth.uid()); RLS keeps users apart.
-- No API keys are stored here: the Gemini key stays in the phone's encrypted storage.

create table if not exists public.pb_bots (
  user_id uuid not null references auth.users (id) on delete cascade,
  bot_id text not null,
  data jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (user_id, bot_id)
);

create table if not exists public.pb_messages (
  id bigserial primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  client_id text not null,            -- 'pc:<local id>' or 'phone:<uuid>' (dedupe key)
  session text not null,
  role text not null check (role in ('user', 'assistant')),
  text text not null,
  origin text not null default 'pc' check (origin in ('pc', 'phone')),
  ts double precision not null,
  created_at timestamptz not null default now(),
  unique (user_id, client_id)
);
create index if not exists pb_messages_user_session_idx on public.pb_messages (user_id, session, ts);
create index if not exists pb_messages_user_id_idx on public.pb_messages (user_id, id);

alter table public.pb_bots enable row level security;
alter table public.pb_messages enable row level security;

revoke all on public.pb_bots, public.pb_messages from anon;
grant select, insert, update, delete on public.pb_bots, public.pb_messages to authenticated;
grant usage, select on sequence public.pb_messages_id_seq to authenticated;
grant all on public.pb_bots, public.pb_messages to postgres, service_role;

drop policy if exists "pb_bots_own" on public.pb_bots;
create policy "pb_bots_own" on public.pb_bots for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "pb_messages_own" on public.pb_messages;
create policy "pb_messages_own" on public.pb_messages for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
