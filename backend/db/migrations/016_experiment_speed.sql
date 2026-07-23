-- v4.0 perf: allow sub-hour metric windows for fast experiments and demos.
-- Was int (min 1 hour); numeric lets us set 0.0833 for a 5-minute window.

alter table experiments
  alter column metric_window_hours type numeric using metric_window_hours::numeric;

-- Skip-governance path for orchestrator-driven creatives — real spend still
-- goes through sightengine/judge; mock + sandbox experiments can skip.
alter table campaigns
  add column if not exists skip_governance boolean not null default false;
