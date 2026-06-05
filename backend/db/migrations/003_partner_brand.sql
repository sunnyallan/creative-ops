-- v1.3: partnership offers — co-branded creatives

alter table campaigns
  add column if not exists partner_brand jsonb;
  -- shape: {"name": str, "logo_path": str | null, "primary_colour": str | null}
