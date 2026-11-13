// Project settings. The anon key is meant to be public: the row-level security
// policies in supabase/migrations are what protect the data.
window.IVY_CONFIG = {
  supabaseUrl: 'https://YOUR-PROJECT.supabase.co',
  supabaseAnonKey: 'YOUR-ANON-KEY',

  // Where the map opens before any observations load (Pittsburgh).
  mapCenter: [40.4406, -79.9959],
  mapZoom: 12,

  // Longest side of an uploaded photo, in pixels.
  photoMaxSide: 1280,
};
