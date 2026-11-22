# Supabase migration workflow

This directory is the canonical home for future, ordered SQL migrations. No migration is applied by this Sprint 1 branch.

## Current baseline

The repository currently contains legacy SQL scripts at the root of this directory:

- `../schema.sql` — dashboard paper-trading state and events.
- `../market_scanner_v1.sql` — scanner paper portfolio, candidate/run/signal tables and worker RPCs.
- `../pmi_v2.sql` — prediction-market intelligence schema and collector.

These scripts were historically documented as SQL Editor/manual setup scripts. The live database migration registry was empty at the time of the project audit, so the repository does not yet have a verified migration baseline. Do not copy these scripts into numbered migrations or apply them blindly: doing so may duplicate objects or conflict with existing production state.

## Naming and process

1. Use UTC timestamp prefixes: `YYYYMMDDHHMMSS_short_description.sql`.
2. One migration should represent one logical, reviewable schema change.
3. Include forward-only DDL, explicit grants/RLS, and rollback notes in the PR description where rollback is safe.
4. Keep service-role credentials server-side; never add secrets to migration files.
5. Validate against a disposable/local Supabase database first, then staging after explicit approval.
6. Review the generated SQL diff and current schema before any remote migration.
7. Apply to production only through a separately approved deployment change.

## CLI safety

Supabase CLI v3 defaults database commands to local. Any future remote operation must name its target explicitly and be reviewed; CI must never infer production as a target. This Sprint 1 work only establishes repository structure and documentation.
