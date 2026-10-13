-- =====================================================================
-- 017 - Syllabi from logged-in users are used at once ("unverified")
-- Kolkata Live Job Search
--
-- New status 'unverified': sent by a logged-in user and used for everyone straight away,
-- shown as "not yet checked". An admin later approves it (-> approved) or removes it (-> rejected).
-- When both exist for the same college + department + semester, the approved one is used first.
-- =====================================================================

alter table public.syllabi drop constraint if exists syllabi_status_check;
alter table public.syllabi add constraint syllabi_status_check
  check (status in ('pending', 'unverified', 'approved', 'rejected', 'archived'));

-- finding the syllabus in use for a college + department quickly
create index if not exists syllabi_in_use_idx on public.syllabi (college_id, lower(department), semester)
  where status in ('approved', 'unverified');
