# Training the ivy model

Everything here runs on your own computer. No GPU is needed.

The model sorts a camera frame into four classes:

| Class | Meaning |
|---|---|
| `ivy_climbing` | Ivy on a trunk, wall or fence |
| `ivy_ground` | Ivy foliage with no trunk in view |
| `other_vegetation` | Any other plant, and trunks without ivy |
| `no_vegetation` | Pavement, walls, sky, indoors |

The phone raises an alert when the two ivy scores together pass a threshold.

## The pipeline

```
download_inat.py ──► data/inat/ ──► sort_photos.py ──► data/labels/hedera.csv ─┐
                                                                               ├─► build_dataset.py ──► data/dataset/
capture app ──► Supabase ──► pull_field_photos.py ──► data/field/ ─────────────┘            │
                                                                                            ▼
                                             app/model/v1/  ◄── export ◄── train.py ──► ml/runs/v1/report.html
```

`data/` and `ml/runs/` stay on your computer and are not committed. Only the
small exported model in `app/model/` goes into the repository.

## One-time setup

You need Python 3.10 to 3.13 on Windows, Linux, or a Mac with Apple silicon.
The pinned TensorFlow has no build for Intel Macs.

```bash
git clone https://github.com/kristoferfosmoe/ivy-finder.git
```

```bash
cd ivy-finder
```

```bash
python -m venv .venv
```

Activate the environment. On Mac or Linux:

```bash
source .venv/bin/activate
```

On Windows:

```bash
.venv\Scripts\activate
```

Then install, in two steps (see the note in `requirements.txt` for why):

```bash
pip install -r ml/requirements.txt
```

```bash
pip install --no-deps tensorflowjs==4.22.0
```

Activate the environment again each time you open a new terminal.

## Step 1: download public photos

```bash
python ml/download_inat.py
```

Fetches about 8,000 photos from iNaturalist taken within 500 km of
Pittsburgh: 3,000 of ivy and 5,000 of look-alikes, trees, moss and ordinary
plants. Allow 20 to 40 minutes and 2 GB of disk. You can stop it and run it
again; it carries on where it left off.

To try the whole pipeline quickly first, add `--scale 0.1` for a tenth of the
photos.

## Step 2: sort the ivy photos

```bash
python ml/sort_photos.py
```

A page opens in your browser with 24 ivy photos at a time. Each starts as
GROUND. Click a photo once for CLIMBING, twice for REJECT. Press Enter to save
the page and see the next. 3,000 photos is 125 pages, around half an hour.
Progress saves after every page, so you can do it in sittings.

- **Climbing**: ivy on a trunk, wall or fence, even a single stem, and even if
  ground ivy is also in the picture.
- **Ground**: ivy leaves with no trunk or wall in view. Leaf close-ups go here.
- **Reject**: you can't tell it is ivy, flowers or berries fill the frame, a
  potted plant, a drawing, or too dark to see.

When unsure between climbing and ground, ask whether a trunk or wall is
visible. Don't agonise: a few mistakes among thousands do no harm.

## Step 3: take field photos

This needs the capture app working (Supabase and GitHub Pages set up; see the
main README). It is the step that most affects how well the model works on
your phone, because downloaded photos are tidier than real video frames.

Hold the phone the way you will when scanning: upright, at walking distance,
subject inside the dashed square. Pick the tag before you shoot; the app keeps
your choice, so a run of similar photos is one tap each.

| Tag in the app | Target | What to shoot |
|---|---|---|
| Ivy, climbing or both | 300+ over 40+ trees | Each tree from 2, 5 and 10 metres and from two sides. Include thick bare stems low on the trunk. |
| Ivy, ground | 150+ over 15+ patches | Carpets and edges of carpets, from standing height. |
| Trunk, no ivy | 200+ | Bare bark of many species, mossy and lichen-covered trunks, trunks with other vines. |
| Look-alike | 100+ | Wintercreeper above all. Also Virginia creeper, poison ivy (don't touch), pachysandra, periwinkle. |
| Other plants | 150+ | Shrubs, lawn, leaf litter, ferns, hedges. |
| No plants | 200+ | Pavement, walls, fences, cars, sky, your feet, indoors. |

Two things matter more than the totals:

- **Variety of places.** Photos taken within about 50 metres of each other are
  treated as one place, and a quarter of the places are held back to test the
  model. Twenty photos of one tree teach it less than two photos each of ten
  trees. Aim for at least 30 separate places overall.
- **Variety of conditions.** Sun, shade, overcast, wet bark, different
  distances.

Then copy them to your computer:

```bash
python ml/pull_field_photos.py you@example.com
```

It asks for the password you use in the app. Run it again any time you have
taken more photos.

## Step 4: build the dataset

```bash
python ml/build_dataset.py
```

Prints a table of photo counts per class and warns about anything too thin.
Read the notes it prints: they tell you what to go and photograph next.

## Step 5: train

```bash
python ml/train.py --name v1
```

Takes 20 to 30 minutes on a four-core computer. When it finishes:

- Open `ml/runs/v1/report.html`. The "Field test" section is the honest
  score: your own photos from places the model never saw. Below it are
  galleries of the ivy it missed and the false alarms, worst first.
- `app/model/v1/` holds the model for the phone. Commit and push that folder
  when you are happy with the report.

## Step 6: improve it

The report's "False alarms by kind of photo" table and the two galleries show
what fools the model. Go and photograph more of exactly that with the right
tag, then rerun steps 3 (the pull), 4 and 5 with a new name such as `v2`.
Two or three rounds usually make the biggest difference.

## Reading the report

- **Catches N% of ivy**: of the photos that really show ivy, how many would
  raise an alert. The threshold is set to keep this at 90% or higher.
- **N% of alerts are ivy**: of the photos that raise an alert, how many really
  show ivy. The rest are false alarms.
- A model that looks excellent on validation but poor on the field test has
  learned what downloaded photos look like, not what your camera sees. The
  cure is more field photos.

## What to expect

A trial run on 2,800 downloaded photos, with all ivy as one class and no field
photos, caught 91% of ivy with 86% of alerts correct. Its false alarms were
mostly wintercreeper, Boston ivy, ground ivy and tree trunks; its misses were
berry close-ups, bare stems and distant trunks. Expect lower numbers on your
own field photos at first, improving as you add them.

## Notes

- Live detection must prepare each video frame the way training does: take the
  centre square, shrink it to 320 px, then resize to 224 px.

- Photo authors and licences are recorded in `data/inat/manifest.csv`. The
  licences allow non-commercial reuse with credit; keep that file if you ever
  share the photos.
- To score an existing model again after changing the dataset:
  `python ml/evaluate.py --name v1`.
- On an Intel Mac, or if training is too slow, run steps 4 and 5 in Google
  Colab instead: upload the `data/` folder to Google Drive, clone the repo in
  a notebook, link `data/` into it and run the same commands. This route has
  not been tested.
