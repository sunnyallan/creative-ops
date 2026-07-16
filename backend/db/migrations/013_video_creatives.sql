-- v4.0 Phase D: Video creatives (Veo)
--
-- We keep the existing `storage_path` semantic (the row's "canonical thumbnail-ish
-- preview" used everywhere in the UI), and add explicit video_path + thumbnail_path
-- for video rows. For image rows, media_type stays 'image' and video_path is null.

alter table creatives
  add column if not exists media_type text not null default 'image', -- 'image' | 'video'
  add column if not exists video_path text,                          -- mp4 in Storage
  add column if not exists thumbnail_path text,                      -- extracted frame preview
  add column if not exists duration_seconds numeric;                 -- for player + reporting

alter table campaigns
  add column if not exists media_type text not null default 'image'; -- what THIS campaign asks for

-- Reduce accidental crashes when someone filters creatives by format
create index if not exists creatives_media_type_idx on creatives(media_type);
