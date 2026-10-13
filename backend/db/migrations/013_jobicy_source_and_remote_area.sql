-- =====================================================================
-- 013 - Allow jobs from Jobicy (remote jobs open to India)
-- Kolkata Live Job Search
-- Work-from-home jobs get the area 'Work from home' (area has no fixed list, so nothing to change there).
-- =====================================================================
alter table public.jobs drop constraint if exists jobs_source_check;
alter table public.jobs add constraint jobs_source_check
  check (source in ('greenhouse', 'lever', 'ashby', 'smartrecruiters', 'workable',
                    'adzuna', 'jooble', 'careerjet', 'jobicy', 'career_page', 'indian_ats',
                    'government', 'campus', 'community', 'employer'));
