-- =====================================================================
-- 008 - AI embeddings (semantic job matching)
-- Kolkata Live Job Search
-- =====================================================================
-- Every open job and every saved CV gets a 384-number "meaning" vector from the
-- all-MiniLM-L6-v2 model. embedding_hash remembers WHICH text (and model) the
-- vector was made from, so a job is embedded again only when its text changes.

alter table public.jobs add column if not exists embedding_hash text;
alter table public.cvs  add column if not exists embedding_hash text;

comment on column public.jobs.embedding_hash is 'Hash of model + job text used for the embedding. Changes when the job text changes.';
comment on column public.cvs.embedding_hash  is 'Hash of model + CV text used for the embedding.';

-- record which embedding model the app uses (shown in the Admin Panel)
insert into public.model_versions (model_name, version, is_active, notes)
values ('text_embedding', 'all-MiniLM-L6-v2', true, 'fastembed (ONNX), 384 dimensions, cosine similarity')
on conflict do nothing;
