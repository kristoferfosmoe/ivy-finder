"""Names and paths shared by the dataset and training scripts."""

from pathlib import Path

# Order is the model's output order. Do not reorder once a model is in use.
CLASSES = ["ivy_climbing", "ivy_ground", "other_vegetation", "no_vegetation"]
IVY_CLASSES = ["ivy_climbing", "ivy_ground"]

INPUT_SIZE = 224  # pixels, square; must match the browser's resize

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

INAT_DIR = DATA / "inat"                  # downloaded iNaturalist photos
INAT_MANIFEST = INAT_DIR / "manifest.csv"
HEDERA_LABELS = DATA / "labels" / "hedera.csv"  # output of sort_photos.py
FIELD_DIR = DATA / "field"                # photos pulled from Supabase
FIELD_MANIFEST = FIELD_DIR / "manifest.csv"
DATASET_DIR = DATA / "dataset"            # built by build_dataset.py
DATASET_INDEX = DATASET_DIR / "index.csv"

RUNS_DIR = REPO / "ml" / "runs"           # training outputs, not committed
APP_MODEL_DIR = REPO / "app" / "model"    # exported browser models, committed
