# Ivy Finder

A phone web app for finding and recording ivy (*Hedera*), with a map for
monitoring it. A prototype, not a production system.

The site is plain static files with no build step. GitHub Pages serves it and
Supabase stores the observations and photos.

| Path | What it is |
|---|---|
| `app/` | Capture app: camera, GPS, tags, upload with an on-phone retry queue |
| `dashboard/` | Map of observations, status updates, CSV and GeoJSON export |
| `spike/` | Speed test: how fast a phone runs the detector's model architecture |
| `supabase/migrations/` | Database schema and access rules |
| `ml/` | Model export to the browser format |
| `shared/`, `vendor/`, `config.js` | Styles, sign-in, pinned libraries, project settings |

## Status

Built: capture, upload, map, speed test, model export.
Not built yet: the ivy model itself and live detection on the video feed.
The capture app is the tool for collecting the training photos that model needs.

## Setup

### 1. Supabase

1. Create a project.
2. In the SQL editor, paste and run `supabase/migrations/0001_init.sql`.
3. Under Authentication, turn off new sign-ups, then add each surveyor as a
   user with an email and password. Anyone who can sign in can read every
   observation and change its status, so only add people you trust.
4. Copy the project URL and anon key into `config.js`. The anon key is meant to
   be public; the access rules in the migration are what protect the data.

### 2. GitHub Pages

In the repository settings, under Pages, choose "Deploy from a branch", pick the
branch and the root folder. Pages on a private repository needs a paid GitHub
plan. Camera and location only work over HTTPS, which Pages provides.

### 3. Phones

Open the Pages URL, run the speed test first, then sign in to the capture app.
"Add to Home Screen" gives it a full-screen icon. Allow camera and location
when asked.

## Collecting training photos

The capture app remembers its settings between shots, so a run of similar
photos is one tap each. Every photo is tagged with what it shows:

- **Ivy**, with growth form (climbing, ground, both) and, for climbing ivy, how
  far up the trunk it reaches. These are the monitoring records and need a GPS
  fix.
- **Look-alike**, **Trunk, no ivy**, **Other plants**, **No plants**. These are
  negative examples for training and are hidden from the map by default.

The dashed square in the viewfinder is the part of the frame the model will
see, so frame the subject inside it.

What to aim for:

- Climbing ivy on at least 30 to 50 different trees, at walking distance, in
  varied light. Include thick leafless stems where the foliage is high up.
- Trunks without ivy: bare, mossy, lichen-covered, and carrying other vines.
- Look-alikes common in western Pennsylvania. Wintercreeper is the important
  one, because it is also evergreen and climbs trunks. Others: Virginia
  creeper, poison ivy (hairy vine; photograph it, don't touch it), Boston ivy,
  oriental bittersweet, wild grape, Japanese honeysuckle, periwinkle,
  pachysandra, ground ivy.

## Model export

`ml/export_tfjs.py` converts a Keras model to the format the site loads. See
`ml/requirements.txt` for the pinned versions and the two-step install.

```bash
python ml/export_tfjs.py --stock --out spike/model
```

Two things in that script are there for a reason and should stay:

- It turns off oneDNN before TensorFlow loads. Otherwise the exported graph
  contains a fused hard-swish activation that the browser's WebGL backend
  cannot run, and it fails on the first prediction.
- It stubs three packages the converter imports but never uses for this kind
  of model, because they have no build matching current TensorFlow.

The exported model scales pixels itself, so the browser feeds it raw 0 to 255
RGB values.

## Known limits

- The capture app needs a connection to load. Once open it keeps working
  without one and uploads when the connection returns.
- Photos are resized to 1280 px on the long side, about 100 to 300 KB each.
- Map tiles come from OpenStreetMap's public server, which is fine for light
  personal use only.
