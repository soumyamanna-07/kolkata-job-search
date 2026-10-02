-- =====================================================================
-- 006 - Security: Row Level Security + no direct public table access
--       + private storage bucket for CVs
-- Kolkata Live Job Search
--
-- Design: the browser NEVER reads tables directly. All data goes through
-- our FastAPI backend, which checks the logged-in user and their role.
-- So public roles (anon, authenticated) get NO table access at all, and
-- RLS is ON for every table as a second safety layer (deny by default).
-- =====================================================================

-- ---------- 1. Row Level Security ON for every table ----------
alter table public.profiles             enable row level security;
alter table public.companies            enable row level security;
alter table public.jobs                 enable row level security;
alter table public.cvs                  enable row level security;
alter table public.saved_jobs           enable row level security;
alter table public.job_alerts           enable row level security;
alter table public.job_events           enable row level security;
alter table public.employer_profiles    enable row level security;
alter table public.job_submissions      enable row level security;
alter table public.job_reports          enable row level security;
alter table public.job_link_submissions enable row level security;
alter table public.pipeline_runs        enable row level security;
alter table public.admin_actions        enable row level security;
alter table public.model_versions       enable row level security;

-- ---------- 2. Remove any direct table access for public roles ----------
revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;

-- future tables also start with no public access
alter default privileges in schema public revoke all on tables    from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;

-- internal trigger functions must not be callable from the outside
revoke execute on function public.handle_new_user() from public, anon, authenticated;
revoke execute on function public.set_updated_at()  from public, anon, authenticated;

-- ---------- 3. Private storage bucket for CV files ----------
-- Not public, PDF/DOCX only, max 5 MB. Only the backend (service key) can read/write.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'cvs', 'cvs', false, 5242880,
  array['application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
)
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;