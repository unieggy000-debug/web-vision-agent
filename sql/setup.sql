-- One-time setup for YOUR Supabase project.
-- Dashboard: Database → Extensions → enable "vector"
-- Then: SQL Editor → paste this file → Run

create extension if not exists vector with schema extensions;

create table if not exists public.research_cases (
  id text primary key,
  title text,
  url text unique,
  screenshots jsonb default '[]'::jsonb,
  visual jsonb default '{}'::jsonb,
  interaction jsonb default '{}'::jsonb,
  frontend jsonb default '{}'::jsonb,
  replication jsonb default '{}'::jsonb,
  embedding extensions.vector(384),
  created_at timestamptz default now()
);

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

-- Personal-use RLS: this machine talks to YOUR project with the anon key.
-- If you share that key, anyone can read/write this table.
alter table public.research_cases enable row level security;

drop policy if exists research_cases_personal_all on public.research_cases;
create policy research_cases_personal_all
  on public.research_cases
  for all
  using (true)
  with check (true);
