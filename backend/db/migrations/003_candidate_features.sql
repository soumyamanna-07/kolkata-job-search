-- =====================================================================
-- 003 - Candidate features: CVs, saved jobs, job alerts, activity events
-- Kolkata Live Job Search
-- =====================================================================

-- ---------- CVs: parsed data from a candidate's uploaded CV ----------
-- Privacy: we keep only what matching needs (skills, experience, education,
-- embedding). The original file is optional and lives in a PRIVATE bucket.
create table public.cvs (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references public.profiles (id) on delete cascade,
  file_name        text,
  storage_path     text,                          -- null = file not saved (only parsed data kept)
  skills           text[] not null default '{}',
  experience_years numeric(4, 1) check (experience_years >= 0),
  education        text,
  job_titles       text[] not null default '{}', -- past/current roles found in the CV
  embedding        extensions.vector(384),
  is_active        boolean not null default true,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

comment on table public.cvs is 'Parsed CV data used for matching. Only one active CV per user.';

create index cvs_user_id_idx on public.cvs (user_id);
create unique index cvs_one_active_per_user on public.cvs (user_id) where is_active;

create trigger cvs_set_updated_at
before update on public.cvs
for each row execute function public.set_updated_at();

-- ---------- Saved jobs ----------
create table public.saved_jobs (
  user_id    uuid not null references public.profiles (id) on delete cascade,
  job_id     uuid not null references public.jobs (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, job_id)
);

create index saved_jobs_job_id_idx on public.saved_jobs (job_id);

-- ---------- Job alerts: notify when a new matching job opens ----------
create table public.job_alerts (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.profiles (id) on delete cascade,
  name         text not null,
  filters      jsonb not null default '{}'::jsonb,  -- e.g. {"keywords":"python","area":"Salt Lake","salary_min":400000}
  use_cv_match boolean not null default false,       -- alert on jobs that match the active CV
  channel      text not null default 'email' check (channel in ('email', 'telegram')),
  frequency    text not null default 'daily' check (frequency in ('instant', 'daily', 'weekly')),
  is_active    boolean not null default true,
  last_sent_at timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index job_alerts_user_id_idx on public.job_alerts (user_id);
create index job_alerts_active_idx on public.job_alerts (is_active, frequency);

create trigger job_alerts_set_updated_at
before update on public.job_alerts
for each row execute function public.set_updated_at();

-- ---------- Job events: what users do with jobs ----------
-- Powers "applied history", analytics and ML ranking feedback.
-- If a user deletes their account, their events stay only as anonymous data.
create table public.job_events (
  id            bigint generated always as identity primary key,
  user_id       uuid references public.profiles (id) on delete set null,
  session_id    text,                              -- anonymous id for guest users
  job_id        uuid not null references public.jobs (id) on delete cascade,
  event_type    text not null
                check (event_type in ('impression', 'view', 'click_apply', 'save', 'unsave', 'hide')),
  source_page   text check (source_page in ('search', 'cv_match', 'recommendations', 'alert', 'assistant', 'job_page')),
  rank_position integer check (rank_position >= 1),
  match_score   numeric(5, 2) check (match_score between 0 and 100),
  model_version text,
  created_at    timestamptz not null default now()
);

create index job_events_user_idx    on public.job_events (user_id, created_at desc);
create index job_events_job_idx     on public.job_events (job_id);
create index job_events_type_idx    on public.job_events (event_type, created_at desc);