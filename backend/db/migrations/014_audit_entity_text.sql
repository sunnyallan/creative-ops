-- v4.0 fix: audit_log.entity_id was uuid, but the Meta OAuth flow stores
-- non-UUID identifiers there (the OAuth state token, Meta's numeric user id).
-- Widen to text — existing uuid values cast losslessly.

alter table audit_log
  alter column entity_id type text using entity_id::text;
