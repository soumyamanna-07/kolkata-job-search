-- =====================================================================
-- 011 - Recruiters: company HR or recruitment agency
-- Kolkata Live Job Search
-- An agency posts jobs for client companies: the job shows the client's
-- name, with "via <agency>" so candidates know who they deal with.
-- =====================================================================
alter table public.employer_profiles
  add column if not exists account_kind text not null default 'company';

do $$ begin
  alter table public.employer_profiles
    add constraint employer_profiles_account_kind_ok check (account_kind in ('company', 'agency'));
exception when duplicate_object then null; end $$;

alter table public.job_submissions
  add column if not exists hiring_for text;          -- client company (agency posts only)

alter table public.jobs
  add column if not exists posted_by text;           -- agency name when an agency posted it

comment on column public.employer_profiles.account_kind is 'company = in-house HR, agency = recruitment agency';
comment on column public.job_submissions.hiring_for is 'agency posts: the client company the job is at';
comment on column public.jobs.posted_by is 'recruitment agency that posted the job (shown as "via ...")';
