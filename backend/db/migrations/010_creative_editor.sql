-- v3.1: In-app creative editor — text-free background + saved text layout

alter table creatives
  add column if not exists edit_background_path text,   -- creative rendered without headline/body/cta
  add column if not exists edit_layout jsonb;           -- saved text-layer positions from the editor
