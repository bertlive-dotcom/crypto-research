-- Market Scanner v1 migration.
-- Run this once in Supabase SQL Editor before deploying the scanner worker.
-- The scanner uses a separate paper portfolio so it cannot race with the
-- dashboard's existing paper_trading_state singleton.

create table if not exists public.scanner_paper_state (
    id text primary key check (id = 'default'),
    state jsonb not null,
    updated_at timestamptz not null default now()
);

create table if not exists public.scanner_runs (
    id bigint generated always as identity primary key,
    status text not null,
    payload jsonb not null,
    created_at timestamptz not null default now()
);

create table if not exists public.market_candidates (
    id bigint generated always as identity primary key,
    symbol text not null,
    score numeric not null,
    eligible boolean not null,
    auto_entry_eligible boolean not null,
    price_usdt numeric not null,
    quote_volume_24h numeric not null,
    change_24h_pct numeric not null,
    features jsonb not null,
    reasons jsonb not null,
    scanned_at timestamptz not null,
    unique (symbol, scanned_at)
);

create index if not exists market_candidates_scanned_at_idx
    on public.market_candidates (scanned_at desc);
create index if not exists market_candidates_score_idx
    on public.market_candidates (score desc);

create table if not exists public.trading_signals (
    signal_id text primary key,
    symbol text not null,
    direction text not null,
    score numeric not null,
    status text not null,
    price_usdt numeric not null,
    stop_price numeric,
    take_profit_price numeric,
    payload jsonb not null,
    created_at timestamptz not null default now()
);

create table if not exists public.market_scanner_lock (
    id text primary key check (id = 'singleton'),
    worker_id text not null,
    lease_until timestamptz not null
);

alter table public.scanner_paper_state enable row level security;
alter table public.scanner_runs enable row level security;
alter table public.market_candidates enable row level security;
alter table public.trading_signals enable row level security;
alter table public.market_scanner_lock enable row level security;

revoke all on public.scanner_paper_state, public.scanner_runs, public.market_candidates,
    public.trading_signals, public.market_scanner_lock from anon, authenticated;
grant select on public.scanner_paper_state, public.scanner_runs, public.market_candidates,
    public.trading_signals to service_role;

create or replace function public.acquire_market_scanner_lock(
    p_worker_id text, p_lease_seconds integer default 240
) returns boolean
language plpgsql security definer set search_path = public
as $$
declare affected_rows integer;
begin
    insert into public.market_scanner_lock (id, worker_id, lease_until)
    values ('singleton', p_worker_id, now() + make_interval(secs => greatest(30, p_lease_seconds)))
    on conflict (id) do update
      set worker_id = excluded.worker_id, lease_until = excluded.lease_until
      where public.market_scanner_lock.lease_until < now()
         or public.market_scanner_lock.worker_id = p_worker_id;
    get diagnostics affected_rows = row_count;
    return affected_rows > 0;
end;
$$;

create or replace function public.release_market_scanner_lock(p_worker_id text)
returns boolean
language plpgsql security definer set search_path = public
as $$
declare affected_rows integer;
begin
    delete from public.market_scanner_lock
     where id = 'singleton' and worker_id = p_worker_id;
    get diagnostics affected_rows = row_count;
    return affected_rows > 0;
end;
$$;

create or replace function public.save_market_scanner_cycle(
    p_state jsonb, p_run jsonb, p_candidates jsonb, p_signals jsonb
) returns void
language plpgsql security definer set search_path = public
as $$
declare item jsonb;
begin
    insert into public.scanner_paper_state (id, state, updated_at)
    values ('default', p_state, now())
    on conflict (id) do update set state = excluded.state, updated_at = now();

    insert into public.scanner_runs (status, payload)
    values (coalesce(p_run->>'status', 'completed'), p_run);

    for item in select value from jsonb_array_elements(coalesce(p_candidates, '[]'::jsonb))
    loop
        insert into public.market_candidates
          (symbol, score, eligible, auto_entry_eligible, price_usdt, quote_volume_24h,
           change_24h_pct, features, reasons, scanned_at)
        values
          (item->>'symbol', (item->>'score')::numeric,
           coalesce((item->>'eligible')::boolean, false),
           coalesce((item->>'auto_entry_eligible')::boolean, false),
           (item->>'price_usdt')::numeric, (item->>'quote_volume_24h')::numeric,
           (item->>'change_24h_pct')::numeric, coalesce(item->'features', '{}'::jsonb),
           coalesce(item->'reasons', '[]'::jsonb), (item->>'scanned_at')::timestamptz)
        on conflict (symbol, scanned_at) do nothing;
    end loop;

    for item in select value from jsonb_array_elements(coalesce(p_signals, '[]'::jsonb))
    loop
        insert into public.trading_signals
          (signal_id, symbol, direction, score, status, price_usdt, stop_price,
           take_profit_price, payload, created_at)
        values
          (item->>'signal_id', item->>'symbol', item->>'direction',
           (item->>'score')::numeric, item->>'status', (item->>'price_usdt')::numeric,
           (item->>'stop_price')::numeric, (item->>'take_profit_price')::numeric,
           item, (item->>'created_at')::timestamptz)
        on conflict (signal_id) do nothing;
    end loop;
end;
$$;

revoke all on function public.acquire_market_scanner_lock(text, integer) from public, anon, authenticated;
revoke all on function public.release_market_scanner_lock(text) from public, anon, authenticated;
revoke all on function public.save_market_scanner_cycle(jsonb, jsonb, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.acquire_market_scanner_lock(text, integer) to service_role;
grant execute on function public.release_market_scanner_lock(text) to service_role;
grant execute on function public.save_market_scanner_cycle(jsonb, jsonb, jsonb, jsonb) to service_role;
