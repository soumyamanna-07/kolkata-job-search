-- =====================================================================
-- 015 - My applications: a job seeker's own tracker
--       Applied -> Interview -> Offer / Rejected / No reply
-- Kolkata Live Job Search
--
-- One row per (user, job). Created when a logged-in user presses Apply;
-- the user moves it through the stages. Later used for the outcome
-- learning loop and the employer "responsiveness" numbers.
-- Personal data: deleted with the account (cascade from profiles).
-- =====================================================================

create table public.applications (
  user_id    uuid not null references public.profiles (id) on delete cascade,
  job_id     uuid not null references public.jobs (id) on delete cascade,
  status     text not null default 'applied'
             check (status in ('applied', 'interview', 'offer', 'rejected', 'no_reply')),
  note       text check (char_length(note) <= 500),
  applied_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, job_id)
);

create index applications_job_id_idx on public.applications (job_id);
create index applications_status_idx on public.applications (status);

create trigger applications_set_updated_at
before update on public.applications
for each row execute function public.set_updated_at();

-- same rule as every other table: no direct browser access, the backend does all reads and writes
alter table public.applications enable row level security;
revoke all on public.applications from anon, authenticated;

-- jobs that logged-in users already opened with Apply become their first applications
insert into public.applications (user_id, job_id, applied_at, updated_at)
select e.user_id, e.job_id, min(e.created_at), min(e.created_at)
from public.job_events e
join public.profiles p on p.id = e.user_id
where e.event_type = 'click_apply' and e.user_id is not null
group by e.user_id, e.job_id
on conflict (user_id, job_id) do nothing;
