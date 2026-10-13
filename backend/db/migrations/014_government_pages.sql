-- =====================================================================
-- 014 - Government recruitment pages in the Company List
-- Kolkata Live Job Search
-- A company with ats_platform 'government' is a government office or institute whose official
-- recruitment page (careers_url) the pipeline reads every day for current notices.
-- =====================================================================
alter table public.companies drop constraint if exists companies_ats_platform_check;
alter table public.companies add constraint companies_ats_platform_check
  check (ats_platform in ('greenhouse', 'lever', 'ashby', 'smartrecruiters', 'workable', 'zoho_recruit',
                          'freshteam', 'keka', 'darwinbox', 'government', 'other'));
