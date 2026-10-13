-- =====================================================================
-- 012 - Allow jobs from Careerjet (Jooble was already allowed)
-- Kolkata Live Job Search
-- =====================================================================
alter table public.jobs drop constraint if exists jobs_source_check;
alter table public.jobs add constraint jobs_source_check
  check (source in ('greenhouse', 'lever', 'ashby', 'smartrecruiters', 'workable',
                    'adzuna', 'jooble', 'careerjet', 'career_page', 'indian_ats',
                    'government', 'campus', 'community', 'employer'));
