-- =====================================================================
-- 016 - College syllabi, for the Curriculum Gap Report (Stage 1)
-- Kolkata Live Job Search
--
-- colleges           : colleges in and around Kolkata. Users can suggest one; an admin approves
--                      it before it shows in the lists. syllabus_url = where it is published.
-- syllabi            : one syllabus = college + department + batch + (one semester or all)
--                      status: pending (sent by a user, waiting for admin) -> approved / rejected
--                      A "quick check" is NOT stored at all: it is read, compared with live jobs
--                      and shown, then forgotten.
-- syllabus_subjects  : the subjects in it (code, name, semester, theory/lab, elective options,
--                      topics if the syllabus has them) and the skills each subject teaches
--
-- When people choose college + department + semester, the newest APPROVED syllabus is used.
-- Only one approved syllabus per college + department + batch + semester (older ones are archived).
-- =====================================================================

create table public.colleges (
  id            uuid primary key default gen_random_uuid(),
  name          text not null check (char_length(name) between 3 and 200),
  short_name    text check (char_length(short_name) <= 40),
  university    text check (char_length(university) <= 200),      -- e.g. MAKAUT (WBUT)
  city          text check (char_length(city) <= 80),
  website       text check (website ~ '^https?://'),
  syllabus_url  text check (syllabus_url ~ '^https?://'),          -- page / PDF to read automatically (later step)
  status        text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  created_by    uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create unique index colleges_name_key on public.colleges (lower(name));

create table public.syllabi (
  id              uuid primary key default gen_random_uuid(),
  college_id      uuid not null references public.colleges (id) on delete cascade,
  department      text not null check (char_length(department) between 2 and 120),   -- e.g. CSE (AI & ML)
  program         text not null default 'B.Tech' check (char_length(program) <= 40),
  batch           text check (char_length(batch) <= 40),        -- e.g. 2020-21 onwards, 2023-27, R23
  semester        integer check (semester between 1 and 10),     -- null = the whole course (all semesters)
  source          text not null default 'upload' check (source in ('upload', 'website', 'admin')),
  status          text not null default 'pending' check (status in ('pending', 'approved', 'rejected', 'archived')),
  source_url      text check (source_url ~ '^https?://'),
  file_name       text check (char_length(file_name) <= 200),
  raw_text        text check (char_length(raw_text) <= 400000),        -- kept so the admin can check it
  submitted_by    uuid references public.profiles (id) on delete set null,
  reviewed_by     uuid references public.profiles (id) on delete set null,
  review_note     text check (char_length(review_note) <= 1000),
  reviewed_at     timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index syllabi_lookup_idx on public.syllabi (college_id, lower(department), semester, status);
create index syllabi_status_idx on public.syllabi (status, created_at);
-- one approved syllabus per college + department + batch + semester
create unique index syllabi_one_approved_key on public.syllabi
  (college_id, lower(department), lower(coalesce(batch, '')), coalesce(semester, 0))
  where status = 'approved';

create table public.syllabus_subjects (
  id           uuid primary key default gen_random_uuid(),
  syllabus_id  uuid not null references public.syllabi (id) on delete cascade,
  semester     integer check (semester between 1 and 10),
  code         text check (char_length(code) <= 40),
  name         text not null check (char_length(name) between 2 and 300),
  kind         text not null default 'theory' check (kind in ('theory', 'lab', 'project', 'other')),
  is_elective  boolean not null default false,
  options      text[] not null default '{}',              -- elective choices, e.g. {Cloud Computing, Graph Theory}
  credits      numeric(4, 1) check (credits >= 0),
  topics       text check (char_length(topics) <= 20000),  -- unit / topic text, when the syllabus has it
  skills       text[] not null default '{}',              -- skills this subject teaches (filled by the mapper)
  embedding    extensions.vector(384),                    -- AI embedding of name + topics (same model as jobs)
  position     integer not null default 0,
  created_at   timestamptz not null default now()
);
create index syllabus_subjects_syllabus_idx on public.syllabus_subjects (syllabus_id, semester, position);
create index syllabus_subjects_skills_idx on public.syllabus_subjects using gin (skills);

create trigger colleges_set_updated_at before update on public.colleges
for each row execute function public.set_updated_at();
create trigger syllabi_set_updated_at before update on public.syllabi
for each row execute function public.set_updated_at();

-- same rule as every other table: no direct browser access, the backend does all reads and writes
alter table public.colleges          enable row level security;
alter table public.syllabi           enable row level security;
alter table public.syllabus_subjects enable row level security;
revoke all on public.colleges, public.syllabi, public.syllabus_subjects from anon, authenticated;

-- a first college so the lists are not empty
insert into public.colleges (name, short_name, university, city, status)
values ('Techno Main Salt Lake', 'TMSL', 'MAKAUT', 'Kolkata', 'approved')
on conflict do nothing;
