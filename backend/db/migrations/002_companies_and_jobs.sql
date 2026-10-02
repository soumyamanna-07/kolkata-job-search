-- =====================================================================
-- 002 - Companies (source list) and Jobs (the live job table)
-- Kolkata Live Job Search
-- =====================================================================

-- ---------- Companies: Kolkata companies the pipeline collects from ----------
create table public.companies (
  id              uuid primary key default gen_random_uuid(),
  name            text not null,
  normalized_name text not null unique,          -- lower-case, no "pvt ltd" etc.
  website         text,
  careers_url     text,
  ats_platform    text not null default 'other'
                  check (ats_platform in ('greenhouse', 'lever', 'ashby', 'smartrecruiters',
                                          'workable', 'zoho_recruit', 'freshteam', 'keka',
                                          'darwinbox', 'other')),
  ats_token       text,                          -- board token / slug on that platform
  is_active       boolean not null default true,
  notes           text,
  added_by        uuid references public.profiles (id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

comment on table public.companies is 'Kolkata companies and their job-board codes. Managed from the Admin Panel.';

create unique index companies_platform_token_uniq
  on public.companies (ats_platform, ats_token)
  where ats_token is not null;

create trigger companies_set_updated_at
before update on public.companies
for each row execute function public.set_updated_at();

-- ---------- Helper: join skills into one text (needed by the search column) ----------
create or replace function public.skills_to_text(skills text[])
returns text
language sql
immutable
parallel safe
set search_path = ''
as $$ select coalesce(pg_catalog.array_to_string(skills, ' '), '') $$;

-- ---------- Jobs: every job the app can show ----------
create table public.jobs (
  id              uuid primary key default gen_random_uuid(),
  job_key         text not null unique,          -- hash of company+title+area (de-duplication)
  source          text not null
                  check (source in ('greenhouse', 'lever', 'ashby', 'smartrecruiters', 'workable',
                                    'adzuna', 'jooble', 'career_page', 'indian_ats',
                                    'government', 'campus', 'community', 'employer')),
  source_job_id   text,                          -- the job's id on the source website
  company_id      uuid references public.companies (id) on delete set null,
  company_name    text not null,
  title           text not null,
  description     text,
  location_raw    text,                          -- location as the source wrote it
  area            text not null default 'Kolkata',  -- Kolkata / Salt Lake / New Town / Howrah
  apply_url       text not null,
  salary_min      integer check (salary_min >= 0),
  salary_max      integer check (salary_max >= 0),
  salary_currency text not null default 'INR',
  salary_period   text not null default 'year' check (salary_period in ('year', 'month', 'hour')),
  experience_min  numeric(4, 1) check (experience_min >= 0),
  experience_max  numeric(4, 1) check (experience_max >= 0),
  job_type        text check (job_type in ('full_time', 'part_time', 'internship', 'contract', 'temporary')),
  work_mode       text check (work_mode in ('onsite', 'hybrid', 'remote')),
  skills          text[] not null default '{}',
  posted_at       timestamptz,
  first_seen_at   timestamptz not null default now(),
  last_seen_at    timestamptz not null default now(),
  status          text not null default 'open' check (status in ('open', 'closed')),
  closed_at       timestamptz,
  employer_id     uuid references public.profiles (id) on delete set null,  -- set for employer-posted jobs
  embedding       extensions.vector(384),        -- AI embedding of title + skills + description
  search_vector   tsvector generated always as (
                    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(company_name, '')), 'B') ||
                    setweight(to_tsvector('english', public.skills_to_text(skills)), 'B') ||
                    setweight(to_tsvector('english', coalesce(description, '')), 'C')
                  ) stored,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint jobs_salary_range_ok check (salary_min is null or salary_max is null or salary_min <= salary_max),
  constraint jobs_experience_range_ok check (experience_min is null or experience_max is null or experience_min <= experience_max)
);

comment on table public.jobs is 'All jobs from live sources and verified employers. The website only shows status = open.';

-- ---------- Indexes for fast search and filters ----------
create index jobs_status_posted_idx  on public.jobs (status, posted_at desc);
create index jobs_area_idx           on public.jobs (area);
create index jobs_company_id_idx     on public.jobs (company_id);
create index jobs_source_idx         on public.jobs (source);
create index jobs_employer_id_idx    on public.jobs (employer_id);
create index jobs_salary_idx         on public.jobs (salary_min, salary_max);
create index jobs_skills_idx         on public.jobs using gin (skills);
create index jobs_search_idx         on public.jobs using gin (search_vector);
create index jobs_title_trgm_idx     on public.jobs using gin (title extensions.gin_trgm_ops);
create index jobs_company_trgm_idx   on public.jobs using gin (company_name extensions.gin_trgm_ops);
create index jobs_embedding_idx      on public.jobs using hnsw (embedding extensions.vector_cosine_ops);

create trigger jobs_set_updated_at
before update on public.jobs
for each row execute function public.set_updated_at();