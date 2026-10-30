-- Run this SQL once in Supabase SQL Editor.
-- The Streamlit server uses SUPABASE_SERVICE_ROLE_KEY; never expose it in browser code.

create table if not exists public.paper_trading_state (
    id text primary key check (id = 'default'),
    state jsonb not null,
    updated_at timestamptz not null default now()
);

create table if not exists public.paper_trading_events (
    id bigint generated always as identity primary key,
    event_type text not null,
    asset text,
    payload jsonb not null,
    created_at timestamptz not null default now()
);

alter table public.paper_trading_state enable row level security;
alter table public.paper_trading_events enable row level security;

revoke all on public.paper_trading_state from anon, authenticated;
revoke all on public.paper_trading_events from anon, authenticated;
grant select on public.paper_trading_state to service_role;
grant select on public.paper_trading_events to service_role;
grant usage, select on sequence public.paper_trading_events_id_seq to service_role;

create or replace function public.save_paper_trading_state(
    p_state jsonb,
    p_event jsonb default null
) returns void
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.paper_trading_state (id, state, updated_at)
    values ('default', p_state, now())
    on conflict (id) do update
       set state = excluded.state, updated_at = now();

    if p_event is not null then
        insert into public.paper_trading_events (event_type, asset, payload)
        values (
            coalesce(nullif(p_event->>'event_type', ''), 'state_saved'),
            nullif(p_event->>'asset', ''),
            p_event
        );
    end if;
end;
$$;

revoke all on function public.save_paper_trading_state(jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.save_paper_trading_state(jsonb, jsonb) to service_role;
