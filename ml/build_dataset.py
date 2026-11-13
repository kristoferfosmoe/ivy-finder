"""Assemble the training dataset from the downloaded and field photos.

    python ml/build_dataset.py

Reads the iNaturalist photos, your sorting of the ivy photos and your field
photos, then writes resized copies to data/dataset/<split>/<class>/ along
with data/dataset/index.csv. The folder is rebuilt from scratch each time.

How photos are split:

  iNaturalist  85% train, 15% validation, split by observation
  field        60% train, 15% validation, 25% test, split by place

The test set holds field photos only, taken at places the model never saw in
training, because that is the situation the phone app will actually be in.
"""

import argparse
import concurrent.futures
import csv
import hashlib
import shutil

from PIL import Image, ImageOps

from common import (
    CLASSES, DATASET_DIR, DATASET_INDEX, FIELD_DIR, FIELD_MANIFEST,
    HEDERA_LABELS, INAT_DIR, INAT_MANIFEST,
)

SHORT_SIDE = 320  # stored size; training crops 224 px squares out of this
SORT_TO_CLASS = {"ground": "ivy_ground", "climbing": "ivy_climbing"}


def fraction(group):
    """A stable number in [0, 1) for a group, so splits never change between runs."""
    return int(hashlib.md5(group.encode()).hexdigest()[:8], 16) / 0x1_0000_0000


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def collect():
    """Return (items, notes). Each item is one photo with its label and split."""
    items, notes = [], []

    sorting = {row["file"]: row["label"] for row in read_csv(HEDERA_LABELS)}
    unsorted = rejected = 0
    for row in read_csv(INAT_MANIFEST):
        if row["folder"] == "hedera":
            choice = sorting.get(row["file"].split("/", 1)[1])
            if choice is None:
                unsorted += 1
                continue
            if choice == "reject":
                rejected += 1
                continue
            label = SORT_TO_CLASS[choice]
        else:
            label = "other_vegetation"
        group = "inat_" + row["observation_id"]
        items.append({
            "path": INAT_DIR / row["file"], "label": label, "source": "inat", "group": group,
            "split": "val" if fraction(group) < 0.15 else "train",
            "name": f"inat_{row['photo_id']}", "detail": row["folder"],
        })
    if unsorted:
        notes.append(f"{unsorted} ivy photos are not sorted yet and were left out (run sort_photos.py).")
    if rejected:
        notes.append(f"{rejected} ivy photos were rejected during sorting and left out.")

    for row in read_csv(FIELD_MANIFEST):
        position = fraction("field_" + row["group"])
        split = "test" if position < 0.25 else "val" if position < 0.40 else "train"
        items.append({
            "path": FIELD_DIR / row["file"], "label": row["label"], "source": "field",
            "group": "field_" + row["group"], "split": split,
            "name": f"field_{row['observation_id']}", "detail": row["subject"],
        })
    return items, notes


def write_image(item):
    target = DATASET_DIR / item["split"] / item["label"] / f"{item['name']}.jpg"
    try:
        with Image.open(item["path"]) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            scale = SHORT_SIDE / min(image.size)
            if scale < 1:
                image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
            image.save(target, "JPEG", quality=90)
    except (OSError, ValueError):
        return None  # missing or unreadable photo
    return target


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    items, notes = collect()
    if not items:
        raise SystemExit("No photos found. Run download_inat.py and sort_photos.py first.")

    if DATASET_DIR.exists():
        shutil.rmtree(DATASET_DIR)
    for split in ("train", "val", "test"):
        for label in CLASSES:
            (DATASET_DIR / split / label).mkdir(parents=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        written = list(pool.map(write_image, items))

    unreadable = 0
    counts = {}
    with DATASET_INDEX.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        # "detail" is the species folder or the capture app's tag, so the
        # report can say which kinds of photo fool the model.
        writer.writerow(["file", "label", "split", "source", "group", "detail"])
        for item, target in zip(items, written):
            if target is None:
                unreadable += 1
                continue
            writer.writerow([target.relative_to(DATASET_DIR).as_posix(), item["label"], item["split"], item["source"], item["group"], item["detail"]])
            key = (item["label"], item["split"], item["source"])
            counts[key] = counts.get(key, 0) + 1
    if unreadable:
        notes.append(f"{unreadable} photos could not be read and were skipped.")

    columns = [("train", "inat"), ("train", "field"), ("val", "inat"), ("val", "field"), ("test", "field")]
    print(f"\n{'':18}" + "".join(f"{split + ' ' + source:>13}" for split, source in columns))
    for label in CLASSES:
        print(f"{label:18}" + "".join(f"{counts.get((label, split, source), 0):>13}" for split, source in columns))

    has_field = any(source == "field" for _, _, source in counts)
    if not has_field:
        notes.append("No field photos yet, so there is no test set. Scores will be for downloaded photos only.")
    for label in CLASSES:
        train = sum(counts.get((label, "train", source), 0) for source in ("inat", "field"))
        test = counts.get((label, "test", "field"), 0)
        if train == 0:
            notes.append(f"No training photos of {label}: the model cannot learn this class yet.")
        elif train < 150:
            notes.append(f"Only {train} training photos of {label}; aim for 300 or more.")
        if has_field and test < 30:
            notes.append(f"Only {test} field test photos of {label}; the test score for it will not mean much.")
    if notes:
        print("\nNotes:")
        for note in notes:
            print("  - " + note)
    print(f"\nWrote {DATASET_DIR}")


if __name__ == "__main__":
    main()
