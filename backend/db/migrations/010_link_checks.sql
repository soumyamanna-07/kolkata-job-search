-- =====================================================================
-- 010 - Dead-link checker: remember when each apply link was checked
-- Kolkata Live Job Search
-- =====================================================================
alter table public.jobs
  add column if not exists link_checked_at timestamptz,
  add column if not exists link_fail_count integer not null default 0,
  add column if not exists close_reason    text;

comment on column public.jobs.link_fail_count is 'dead-link checks failed in a row; 3 = job closed';
comment on column public.jobs.close_reason is 'why the job closed, e.g. dead_link (null = not recorded)';

create index if not exists jobs_link_check_idx
  on public.jobs (source, link_checked_at) where status = 'open';
