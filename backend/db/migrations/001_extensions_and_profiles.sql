-- =====================================================================
-- 001 - Extensions, helper functions and user profiles
-- Kolkata Live Job Search
-- =====================================================================

-- ---------- Extensions ----------
-- vector  : stores AI embeddings for job/CV matching
-- pg_trgm : fuzzy text matching (company names, typo-tolerant search)
create extension if not exists vector with schema extensions;
create extension if not exists pg_trgm with schema extensions;

-- ---------- Helper: keep updated_at current on every UPDATE ----------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------- Profiles: one row per signed-up user ----------
create table public.profiles (
  id                 uuid primary key references auth.users (id) on delete cascade,
  full_name          text,
  role               text not null default 'candidate'
                     check (role in ('candidate', 'employer', 'admin')),
  is_blocked         boolean not null default false,
  privacy_consent_at timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

comment on table public.profiles is 'App-level data for each user. Login itself is handled by Supabase Auth (auth.users).';

create index profiles_role_idx on public.profiles (role);

create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

-- ---------- Auto-create a profile when someone signs up ----------
-- Sign-up can request 'employer'; 'admin' can NEVER be self-assigned.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, full_name, role)
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name'),
    case when new.raw_user_meta_data ->> 'account_type' = 'employer'
         then 'employer' else 'candidate' end
  );
  return new;
end;
$$;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();