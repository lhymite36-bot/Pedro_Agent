-- Phone skip-link: current PC tunnel URL. Safe to re-run.
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
