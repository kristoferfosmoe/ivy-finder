// Project settings. The anon key is meant to be public: the row-level security
// policies in supabase/migrations are what protect the data.
window.IVY_CONFIG = {
  supabaseUrl: 'https://wocbpqvhuojylwsbaiow.supabase.co',
  supabaseAnonKey: 'sb_publishable_AgQffsmHCGEeZ8Axm-T_BA_xo4vtKzV',

  // Where the map opens before any observations load (Pittsburgh).
  mapCenter: [40.4406, -79.9959],
  mapZoom: 12,

  // Folder under app/model/ holding the detector the capture app loads.
  // Set to null to turn live detection off.
  modelVersion: 'v1',

  // Longest side of an uploaded photo, in pixels.
  photoMaxSide: 1280,
};
