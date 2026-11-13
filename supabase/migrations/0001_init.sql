-- Ivy Finder schema. Paste into the Supabase SQL editor and run once.
--
-- Access model: anyone who can sign in is a trusted surveyor. Sign-ups should
-- be disabled in the Supabase dashboard and users created by hand, because the
-- site and its anon key are public and these policies are the only gate.

create table public.observations (
  id            uuid primary key,              -- generated on the phone so retries are safe
  created_at    timestamptz not null default now(),
  captured_at   timestamptz not null,
  observer      uuid not null default auth.uid() references auth.users (id),

  -- What the photo shows. Only 'ivy' rows are monitoring records; the rest are
  -- negative examples collected for model training.
  subject       text not null check (subject in
                  ('ivy', 'lookalike', 'trunk_no_ivy', 'other_vegetation', 'no_vegetation')),
  growth_form   text check (growth_form in ('climbing', 'ground', 'both')),
  trunk_height  text check (trunk_height in ('base', 'mid_trunk', 'canopy')),
  mature        boolean not null default false, -- flowers or berries present
  vines_cut     boolean not null default false,
  notes         text,

  lat           double precision check (lat between -90 and 90),
  lon           double precision check (lon between -180 and 180),
  accuracy_m    real,
  photo_path    text not null,

  status        text not null default 'reported' check (status in
                  ('reported', 'verified', 'treated', 'removed')),

  -- Filled in once on-device detection exists.
  model_version text,
  model_class   text,
  model_score   real,
  user_confirmed boolean,

  constraint ivy_has_growth_form check (subject <> 'ivy' or growth_form is not null),
  constraint ivy_has_location    check (subject <> 'ivy' or (lat is not null and lon is not null)),
  constraint location_is_paired  check ((lat is null) = (lon is null))
);

create index observations_captured_at_idx on public.observations (captured_at desc);

alter table public.observations enable row level security;

create policy "signed-in users read observations"
  on public.observations for select to authenticated
  using (true);

create policy "signed-in users add their own observations"
  on public.observations for insert to authenticated
  with check (observer = auth.uid());

create policy "signed-in users update observations"
  on public.observations for update to authenticated
  using (true)
  with check (true);

create policy "observers delete their own observations"
  on public.observations for delete to authenticated
  using (observer = auth.uid());

-- Photos live in a private bucket at <user id>/<observation id>.jpg and are
-- shown through short-lived signed URLs.
insert into storage.buckets (id, name, public)
values ('photos', 'photos', false)
on conflict (id) do nothing;

create policy "signed-in users read photos"
  on storage.objects for select to authenticated
  using (bucket_id = 'photos');

create policy "signed-in users upload into their own folder"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'photos' and (storage.foldername(name))[1] = auth.uid()::text);

create policy "observers delete their own photos"
  on storage.objects for delete to authenticated
  using (bucket_id = 'photos' and (storage.foldername(name))[1] = auth.uid()::text);
