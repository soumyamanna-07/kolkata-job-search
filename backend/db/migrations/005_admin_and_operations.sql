-- =====================================================================
-- 005 - Admin panel and operations: reports, submitted links,
--       pipeline runs, admin audit log, ML model versions
-- Kolkata Live Job Search
-- =====================================================================

-- ---------- Job reports: "Report this job" from users ----------
create table public.job_reports (
  id          uuid primary key default gen_random_uuid(),
  job_id      uuid not null references public.jobs (id) on delete cascade,
  reporter_id uuid references public.profiles (id) on delete set null,
  reason      text not null
              check (reason in ('spam', 'fake', 'already_closed', 'wrong_location', 'wrong_details', 'other')),
  details     text,
  status      text not null default 'open' check (status in ('open', 'resolved', 'dismissed')),
  resolved_by uuid references public.profiles (id) on delete set null,
  resolved_at timestamptz,
  created_at  timestamptz not null default now()
);

create index job_reports_queue_idx on public.job_reports (status, created_at);
create index job_reports_job_idx   on public.job_reports (job_id);
-- one report per user per job (stops report spamming)
create unique index job_reports_one_per_user on public.job_reports (job_id, reporter_id) where reporter_id is not null;

-- ---------- Job links submitted by users and college TPOs ----------
create table public.job_link_submissions (
  id               uuid primary key default gen_random_uuid(),
  submitted_by     uuid references public.profiles (id) on delete set null,
  submitter_type   text not null default 'user' check (submitter_type in ('user', 'tpo')),
  url              text not null,
  company_name     text,
  title            text,
  note             text,
  status           text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  rejection_reason text,
  reviewed_by      uuid references public.profiles (id) on delete set null,
  reviewed_at      timestamptz,
  published_job_id uuid references public.jobs (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index job_link_submissions_queue_idx on public.job_link_submissions (status, created_at);

create trigger job_link_submissions_set_updated_at
before update on public.job_link_submissions
for each row execute function public.set_updated_at();

-- ---------- Pipeline runs: one row per data-pipeline run (Pipeline Health) ----------
create table public.pipeline_runs (
  id              bigint generated always as identity primary key,
  started_at      timestamptz not null default now(),
  finished_at     timestamptz,
  status          text not null default 'running'
                  check (status in ('running', 'success', 'partial', 'failed')),
  trigger_type    text not null default 'schedule' check (trigger_type in ('schedule', 'manual')),
  total_collected integer not null default 0,
  kolkata_count   integer not null default 0,
  unique_count    integer not null default 0,
  jobs_new        integer not null default 0,
  jobs_updated    integer not null default 0,
  jobs_closed     integer not null default 0,
  source_stats    jsonb not null default '{}'::jsonb,  -- {"lever": {"ok": true, "jobs": 12}, "adzuna": {"ok": false, "error": "..."}}
  error_message   text
);

create index pipeline_runs_started_idx on public.pipeline_runs (started_at desc);

-- ---------- Admin audit log: who did what, when ----------
create table public.admin_actions (
  id           bigint generated always as identity primary key,
  admin_id     uuid references public.profiles (id) on delete set null,
  action       text not null,            -- e.g. approve_submission, block_user, close_job
  target_table text,
  target_id    text,
  details      jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);

create index admin_actions_created_idx on public.admin_actions (created_at desc);
create index admin_actions_admin_idx   on public.admin_actions (admin_id, created_at desc);

-- ---------- ML model versions (Model Monitoring) ----------
create table public.model_versions (
  id         bigint generated always as identity primary key,
  model_name text not null,             -- e.g. match_score, spam_classifier
  version    text not null,             -- e.g. v1-rules, v2-xgboost-2026-11
  metrics    jsonb not null default '{}'::jsonb,  -- {"precision_at_5": 0.72, "auc": 0.81}
  is_active  boolean not null default false,
  notes      text,
  trained_at timestamptz not null default now(),
  unique (model_name, version)
);

-- only one active version per model
create unique index model_versions_one_active on public.model_versions (model_name) where is_active;