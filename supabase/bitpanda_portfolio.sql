-- Bitpanda Portfolio Intelligence: private, read-only account snapshots.
-- Run against the crypto-research production project after reviewing the PR.
-- The dashboard accesses these tables server-side with SUPABASE_SERVICE_ROLE_KEY.

create table if not exists public.bitpanda_sync_runs (
    id bigint generated always as identity primary key,
    status text not null default 'success',
    observed_at timestamptz not null default now(),
    holdings_count integer not null default 0,
    operations_count integer not null default 0,
    earn_configs_count integer not null default 0,
    error text
);

create table if not exists public.bitpanda_holdings_snapshots (
    id bigint generated always as identity primary key,
    asset_id text not null,
    symbol text,
    name text,
    quantity numeric,
    value_eur numeric,
    observed_at timestamptz not null,
    raw_data jsonb not null default '{}'::jsonb,
    unique (asset_id, observed_at)
);

create table if not exists public.bitpanda_operations (
    operation_id text primary key,
    operation_type text,
    status text,
    asset_id text,
    symbol text,
    occurred_at timestamptz,
    raw_data jsonb not null default '{}'::jsonb,
    imported_at timestamptz not null default now()
);

create table if not exists public.bitpanda_portfolio_history (
    id bigint generated always as identity primary key,
    timeframe text not null,
    observed_at timestamptz not null,
    value_eur numeric,
    raw_data jsonb not null default '{}'::jsonb,
    unique (timeframe, observed_at)
);

create table if not exists public.bitpanda_earn_configs (
    config_id text primary key,
    asset_id text,
    apr numeric,
    product_type text,
    mode text,
    enabled boolean,
    soldout boolean,
    observed_at timestamptz not null default now(),
    raw_data jsonb not null default '{}'::jsonb
);

alter table public.bitpanda_sync_runs enable row level security;
alter table public.bitpanda_holdings_snapshots enable row level security;
alter table public.bitpanda_operations enable row level security;
alter table public.bitpanda_portfolio_history enable row level security;
alter table public.bitpanda_earn_configs enable row level security;

revoke all on public.bitpanda_sync_runs from anon, authenticated;
revoke all on public.bitpanda_holdings_snapshots from anon, authenticated;
revoke all on public.bitpanda_operations from anon, authenticated;
revoke all on public.bitpanda_portfolio_history from anon, authenticated;
revoke all on public.bitpanda_earn_configs from anon, authenticated;

grant select, insert, update on public.bitpanda_sync_runs to service_role;
grant select, insert, update on public.bitpanda_holdings_snapshots to service_role;
grant select, insert, update on public.bitpanda_operations to service_role;
grant select, insert, update on public.bitpanda_portfolio_history to service_role;
grant select, insert, update on public.bitpanda_earn_configs to service_role;
grant usage, select on sequence public.bitpanda_sync_runs_id_seq to service_role;
grant usage, select on sequence public.bitpanda_holdings_snapshots_id_seq to service_role;
grant usage, select on sequence public.bitpanda_portfolio_history_id_seq to service_role;
