-- =====================================================================
-- 009 - Record the models/rules the app uses (shown in the Admin Panel)
-- Kolkata Live Job Search
-- =====================================================================
insert into public.model_versions (model_name, version, is_active, notes) values
  ('match_score',   'v1.1-rules',         true, 'Best for You: 45% meaning, 30% skills, 20% experience, 5% freshness'),
  ('spam_check',    'v1-rules',           true, 'Employer job posts: fee requests, easy-money promises, shortened links, ...'),
  ('assistant_llm', 'openai/gpt-oss-20b', true, 'Ask AI answers, via Groq; answers only from retrieved job posts')
on conflict do nothing;
