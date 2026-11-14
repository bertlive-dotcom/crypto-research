-- Market data ingestion v1: additive schema only.
-- Apply to staging first. Existing scanner and paper-trading tables are untouched.
-- All provider data is private and written by backend workers only.

create table if not exists public.market_data_instruments (
    instrument_id text primary key,
    canonical_symbol text not null,
    asset_class text not null check (asset_class in
        ('equity', 'etf', 'index', 'crypto', 'forex', 'commodity', 'future')),
    exchange text,
    currency text,
    display_name text,
    is_active boolean not null default false,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists market_data_instruments_identity_idx
    on public.market_data_instruments
    (asset_class, canonical_symbol, coalesce(exchange, ''));

create table if not exists public.market_data_provider_symbols (
    provider text not null,
    provider_symbol text not null,
    instrument_id text not null references public.market_data_instruments(instrument_id)
        on delete restrict,
    exchange text,
    currency text,
    verification_status text not null default 'pending'
        check (verification_status in ('pending', 'verified', 'rejected', 'unavailable')),
    verified_at timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (provider, provider_symbol)
);

create index if not exists market_data_provider_symbols_instrument_idx
    on public.market_data_provider_symbols (instrument_id, provider);

create table if not exists public.market_data_quotes (
    instrument_id text not null references public.market_data_instruments(instrument_id)
        on delete restrict,
    provider text not null,
    provider_symbol text not null,
    quote_type text not null check (quote_type in
        ('last', 'trade', 'mid', 'bid', 'ask', 'close')),
    observed_at timestamptz not null,
    ingested_at timestamptz not null default now(),
    price numeric not null check (price > 0),
    bid numeric check (bid is null or bid > 0),
    ask numeric check (ask is null or ask > 0),
    currency text,
    exchange text,
    is_delayed boolean,
    quality_status text not null default 'unverified'
        check (quality_status in ('valid', 'stale', 'unverified', 'rejected')),
    payload jsonb not null default '{}'::jsonb,
    primary key (instrument_id, provider, quote_type, observed_at)
);

create index if not exists market_data_quotes_latest_idx
    on public.market_data_quotes (instrument_id, observed_at desc);

create table if not exists public.market_data_candles (
    instrument_id text not null references public.market_data_instruments(instrument_id)
        on delete restrict,
    provider text not null,
    provider_symbol text not null,
    interval text not null,
    opened_at timestamptz not null,
    closed_at timestamptz not null,
    ingested_at timestamptz not null default now(),
    open numeric not null check (open > 0),
    high numeric not null check (high > 0),
    low numeric not null check (low > 0),
    close numeric not null check (close > 0),
    volume numeric check (volume is null or volume >= 0),
    volume_available boolean generated always as (volume is not null) stored,
    currency text,
    exchange text,
    is_closed boolean not null default false,
    quality_status text not null default 'unverified'
        check (quality_status in ('valid', 'stale', 'unverified', 'rejected')),
    payload jsonb not null default '{}'::jsonb,
    primary key (instrument_id, provider, interval, opened_at),
    check (closed_at >= opened_at),
    check (high >= greatest(open, low, close)),
    check (low <= least(open, high, close))
);

create index if not exists market_data_candles_latest_idx
    on public.market_data_candles (instrument_id, interval, opened_at desc);

create table if not exists public.market_data_fundamentals (
    instrument_id text not null references public.market_data_instruments(instrument_id)
        on delete restrict,
    provider text not null,
    metric_key text not null,
    period_end date not null,
    fiscal_period text not null default '',
    reported_at timestamptz,
    observed_at timestamptz not null default now(),
    value numeric,
    currency text,
    quality_status text not null default 'unverified'
        check (quality_status in ('valid', 'stale', 'unverified', 'rejected')),
    payload jsonb not null default '{}'::jsonb,
    primary key (instrument_id, provider, metric_key, period_end, fiscal_period)
);

create index if not exists market_data_fundamentals_latest_idx
    on public.market_data_fundamentals (instrument_id, metric_key, observed_at desc);

create table if not exists public.market_data_provider_runs (
    id bigint generated always as identity primary key,
    provider text not null,
    data_domain text not null,
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    status text not null check (status in
        ('running', 'success', 'partial', 'failed', 'skipped')),
    requests_count integer not null default 0 check (requests_count >= 0),
    records_received integer not null default 0 check (records_received >= 0),
    records_written integer not null default 0 check (records_written >= 0),
    records_rejected integer not null default 0 check (records_rejected >= 0),
    rate_limit_remaining integer,
    error_code text,
    details jsonb not null default '{}'::jsonb
);

create index if not exists market_data_provider_runs_recent_idx
    on public.market_data_provider_runs (provider, started_at desc);

create table if not exists public.market_data_quality_events (
    id bigint generated always as identity primary key,
    provider text,
    instrument_id text references public.market_data_instruments(instrument_id)
        on delete restrict,
    severity text not null check (severity in ('info', 'warning', 'error', 'critical')),
    event_code text not null,
    message text not null,
    observed_at timestamptz not null default now(),
    resolved_at timestamptz,
    payload jsonb not null default '{}'::jsonb
);

create index if not exists market_data_quality_events_recent_idx
    on public.market_data_quality_events (observed_at desc, severity);

-- Private backend-only access. RLS without policies denies client roles.
alter table public.market_data_instruments enable row level security;
alter table public.market_data_provider_symbols enable row level security;
alter table public.market_data_quotes enable row level security;
alter table public.market_data_candles enable row level security;
alter table public.market_data_fundamentals enable row level security;
alter table public.market_data_provider_runs enable row level security;
alter table public.market_data_quality_events enable row level security;

revoke all on public.market_data_instruments,
    public.market_data_provider_symbols,
    public.market_data_quotes,
    public.market_data_candles,
    public.market_data_fundamentals,
    public.market_data_provider_runs,
    public.market_data_quality_events
from public, anon, authenticated;

grant select, insert, update, delete on public.market_data_instruments,
    public.market_data_provider_symbols,
    public.market_data_quotes,
    public.market_data_candles,
    public.market_data_fundamentals,
    public.market_data_provider_runs,
    public.market_data_quality_events
to service_role;

grant usage, select on sequence
    public.market_data_provider_runs_id_seq,
    public.market_data_quality_events_id_seq
to service_role;
