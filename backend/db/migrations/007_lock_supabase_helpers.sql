-- =====================================================================
-- 007 - Lock Supabase's auto-RLS helper function
-- Kolkata Live Job Search
--
-- Supabase creates public.rls_auto_enable() when "Enable automatic RLS"
-- is ticked at project creation. It is a SECURITY DEFINER function, so
-- public roles must not be able to call it. The event trigger that uses
-- it keeps working. Safe to run even if the function does not exist.
-- =====================================================================

do $$
begin
  if exists (
    select 1
    from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'rls_auto_enable'
  ) then
    revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
  end if;
end;
$$;