-- =====================================================================
-- 004 - Employer portal and job verification
-- Kolkata Live Job Search
-- Flow: employer signs up -> admin verifies company -> employer submits
--       job -> auto spam check -> admin approves -> job published to jobs
-- =====================================================================

-- ---------- Employer profiles: company details for employer accounts ----------
create table public.employer_profiles (
  user_id             uuid primary key references public.profiles (id) on delete cascade,
  company_name        text not null,
  official_email      text not null,
  website             text,
  gst_or_cin          text,                        -- optional business ID for verification
  company_id          uuid references public.companies (id) on delete set null,
  verification_status text not null default 'pending'
                      check (verification_status in ('pending', 'approved', 'rejected', 'blocked')),
  rejection_reason    text,
  reviewed_by         uuid references public.profiles (id) on delete set null,
  reviewed_at         timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

comment on table public.employer_profiles is 'Company details of employer accounts. Must be approved by an admin before posting jobs.';

create index employer_profiles_status_idx on public.employer_profiles (verification_status);

create trigger employer_profiles_set_updated_at
before update on public.employer_profiles
for each row execute function public.set_updated_at();

-- ---------- Job submissions: jobs posted by employers, waiting for review ----------
create table public.job_submissions (
  id               uuid primary key default gen_random_uuid(),
  employer_id      uuid not null references public.profiles (id) on delete cascade,
  title            text not null,
  description      text not null,
  skills           text[] not null default '{}',
  location         text,
  area             text not null default 'Kolkata',
  apply_url        text not null,
  salary_min       integer check (salary_min >= 0),
  salary_max       integer check (salary_max >= 0),
  experience_min   numeric(4, 1) check (experience_min >= 0),
  experience_max   numeric(4, 1) check (experience_max >= 0),
  job_type         text check (job_type in ('full_time', 'part_time', 'internship', 'contract', 'temporary')),
  work_mode        text check (work_mode in ('onsite', 'hybrid', 'remote')),
  status           text not null default 'pending'
                   check (status in ('pending', 'approved', 'rejected', 'closed')),
  spam_score       numeric(5, 2) check (spam_score between 0 and 100),  -- set by the auto spam check
  spam_reasons     text[] not null default '{}',                        -- e.g. {asks_for_fee, free_email_domain}
  rejection_reason text,
  reviewed_by      uuid references public.profiles (id) on delete set null,
  reviewed_at      timestamptz,
  published_job_id uuid references public.jobs (id) on delete set null, -- the live job once approved
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint job_submissions_salary_range_ok check (salary_min is null or salary_max is null or salary_min <= salary_max),
  constraint job_submissions_experience_range_ok check (experience_min is null or experience_max is null or experience_min <= experience_max)
);

comment on table public.job_submissions is 'Employer job posts. Nothing goes public until an admin approves it.';

create index job_submissions_employer_idx on public.job_submissions (employer_id, created_at desc);
create index job_submissions_queue_idx    on public.job_submissions (status, spam_score desc, created_at);

create trigger job_submissions_set_updated_at
before update on public.job_submissions
for each row execute function public.set_updated_at();