-- v4.0 post-C: Meta connections become per-brand.
-- Existing rows keep brand_id = NULL which means "tenant default" — the
-- adapter's resolver prefers a brand-specific match, else falls back to
-- the NULL row, else any other row.

alter table meta_connections
  add column if not exists brand_id uuid references brands(id) on delete cascade;

create index if not exists meta_connections_brand_idx
  on meta_connections(tenant_id, brand_id);
