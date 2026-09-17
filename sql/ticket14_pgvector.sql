-- Ticket 14: pgvector semantic memory for research_cases
-- Embedding model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
-- Dimension: 384  (confirmed by running embed_text locally)
--
-- Prefer sql/setup.sql for a new project (creates the table too).
-- Dashboard steps (manual):
-- 1) Open YOUR Supabase project
-- 2) Left sidebar: Database → Extensions
-- 3) Search "vector" → Enable (if not already on)
-- 4) SQL Editor → New query → paste this file → Run
--
-- Note: if embedding column / match_research_cases already exist, this is safe to re-run.

create extension if not exists vector with schema extensions;

alter table public.research_cases
  add column if not exists embedding extensions.vector(384);

create or replace function public.match_research_cases(
  query_embedding extensions.vector(384),
  match_threshold float default 0.3,
  match_count int default 5
)
returns table (
  id text,
  title text,
  url text,
  visual jsonb,
  interaction jsonb,
  frontend jsonb,
  replication jsonb,
  similarity float
)
language sql
stable
as $$
  select
    rc.id,
    rc.title,
    rc.url,
    rc.visual,
    rc.interaction,
    rc.frontend,
    rc.replication,
    (1 - (rc.embedding <=> query_embedding))::float as similarity
  from public.research_cases as rc
  where rc.embedding is not null
    and (1 - (rc.embedding <=> query_embedding)) >= match_threshold
  order by rc.embedding <=> query_embedding
  limit greatest(match_count, 1);
$$;

grant execute on function public.match_research_cases(extensions.vector, float, int)
  to anon, authenticated;

-- Optional: ANN index when the table grows (safe to skip for a few rows).
-- create index if not exists research_cases_embedding_hnsw_idx
--   on public.research_cases
--   using hnsw (embedding extensions.vector_cosine_ops);
