-- =====================================================================
-- 018 - Syllabi fetched from college websites (Stage 1.9)
-- Kolkata Live Job Search
--
-- syllabus_sources : links to a college's syllabus PDF / Word file, added by an admin, each for one
--                    department (+ batch / semester if the file is only for those).
--                    A weekly job reads each link (only if robots.txt allows it). A new or changed
--                    file becomes a syllabus with source 'website' and status 'pending' (Waiting):
--                    it is NOT used until an admin approves it.
-- syllabi.content_hash : SHA-256 of the file, so the same file is never added twice
--                    (also not a file the admin already removed).
-- =====================================================================

create table public.syllabus_sources (
  id               uuid primary key default gen_random_uuid(),
  college_id       uuid not null references public.colleges (id) on delete cascade,
  url              text not null check (url ~ '^https?://' and char_length(url) <= 500),
  department       text not null check (char_length(department) between 2 and 120),
  batch            text check (char_length(batch) <= 40),
  semester         integer check (semester between 1 and 10),        -- null = the whole course
  enabled          boolean not null default true,
  last_checked_at  timestamptz,
  last_status      text check (last_status in ('new', 'unchanged', 'blocked', 'error')),
  last_error       text check (char_length(last_error) <= 500),
  last_hash        text check (char_length(last_hash) = 64),
  created_by       uuid references public.profiles (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create unique index syllabus_sources_url_key on public.syllabus_sources (college_id, lower(url));

alter table public.syllabi add column if not exists content_hash text check (char_length(content_hash) = 64);
create index if not exists syllabi_content_hash_idx on public.syllabi (college_id, content_hash)
  where content_hash is not null;

create trigger syllabus_sources_set_updated_at before update on public.syllabus_sources
for each row execute function public.set_updated_at();

-- same rule as every other table: no direct browser access, the backend does all reads and writes
alter table public.syllabus_sources enable row level security;
revoke all on public.syllabus_sources from anon, authenticated;
