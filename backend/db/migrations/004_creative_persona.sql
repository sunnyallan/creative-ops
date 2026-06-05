-- v1.5: multi-persona campaigns — persist persona on each creative row

alter table creatives
  add column if not exists persona_segment text;

create index if not exists creatives_persona_idx on creatives(persona_segment);
