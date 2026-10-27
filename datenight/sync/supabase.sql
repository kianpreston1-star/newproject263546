-- Date Night Picker: syncing between your phones and laptop.
-- Paste all of this into Supabase (SQL Editor → New query) and press Run. It's safe to run again.
--
-- How it's kept private: the two tables can't be read or written directly from the internet. Apps can
-- only call the four functions below, and every call needs your secret sync code (part of the pairing
-- text the app shows you). Anyone without that code can't see or change anything.

create table if not exists public.datenight_sync (
  code text primary key,
  doc jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default clock_timestamp()
);

create table if not exists public.datenight_photos (
  code text not null,
  name text not null,
  data text not null,
  created_at timestamptz not null default now(),
  primary key (code, name)
);

alter table public.datenight_sync enable row level security;
alter table public.datenight_photos enable row level security;
revoke all on public.datenight_sync from anon, authenticated;
revoke all on public.datenight_photos from anon, authenticated;

create or replace function public.dn_check(p_code text) returns void
language plpgsql immutable as $$
begin
  if p_code is null or p_code !~ '^[A-Za-z0-9_-]{24,64}$' then
    raise exception 'bad sync code';
  end if;
end $$;

-- Everything saved for this code, the names of the photos saved so far, and a version stamp.
create or replace function public.dn_pull(p_code text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  result jsonb;
begin
  perform dn_check(p_code);
  select jsonb_build_object('doc', s.doc, 'version', s.updated_at::text) into result
    from datenight_sync s where s.code = p_code;
  return coalesce(result, jsonb_build_object('doc', '{}'::jsonb, 'version', null))
    || jsonb_build_object('photos', coalesce(
         (select jsonb_agg(p.name) from datenight_photos p where p.code = p_code), '[]'::jsonb));
end $$;

-- Saves only if nobody else saved since this device last looked (otherwise the app fetches and tries again).
create or replace function public.dn_push(p_code text, p_doc jsonb, p_expected text) returns boolean
language plpgsql security definer set search_path = public as $$
declare
  n integer;
begin
  perform dn_check(p_code);
  if length(p_doc::text) > 5000000 then
    raise exception 'too much data';
  end if;
  if p_expected is null then
    insert into datenight_sync (code, doc) values (p_code, p_doc) on conflict (code) do nothing;
  else
    update datenight_sync set doc = p_doc, updated_at = clock_timestamp()
      where code = p_code and updated_at::text = p_expected;
  end if;
  get diagnostics n = row_count;
  return n = 1;
end $$;

create or replace function public.dn_photo_put(p_code text, p_name text, p_data text) returns void
language plpgsql security definer set search_path = public as $$
begin
  perform dn_check(p_code);
  if p_name !~ '^[A-Za-z0-9._-]{1,120}$' or length(p_data) > 3500000 then
    raise exception 'bad photo';
  end if;
  if (select count(*) from datenight_photos where code = p_code) >= 5000 then
    raise exception 'too many photos';
  end if;
  insert into datenight_photos (code, name, data) values (p_code, p_name, p_data)
    on conflict (code, name) do nothing;
end $$;

create or replace function public.dn_photo_get(p_code text, p_names text[]) returns jsonb
language plpgsql security definer set search_path = public as $$
begin
  perform dn_check(p_code);
  return coalesce((select jsonb_object_agg(p.name, p.data) from datenight_photos p
                   where p.code = p_code and p.name = any(p_names[1:10])), '{}'::jsonb);
end $$;

revoke all on function public.dn_pull(text), public.dn_push(text, jsonb, text),
  public.dn_photo_put(text, text, text), public.dn_photo_get(text, text[]) from public;
grant execute on function public.dn_pull(text), public.dn_push(text, jsonb, text),
  public.dn_photo_put(text, text, text), public.dn_photo_get(text, text[]) to anon, authenticated;
