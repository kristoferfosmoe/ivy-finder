"""Download openly licensed iNaturalist photos of ivy and its look-alikes.

    python ml/download_inat.py              # everything, about 9,300 photos
    python ml/download_inat.py --scale 0.1  # a tenth of that, to try it out
    python ml/download_inat.py --only hedera

Only research-grade observations (identity agreed by the community) with a
Creative Commons licence that permits reuse are taken, one photo per
observation. Photos are spread across the twelve months so every season is
represented. Safe to stop and rerun: finished photos are skipped.

Each photo's author and licence is recorded in data/inat/manifest.csv.
"""

import argparse
import concurrent.futures
import csv
import http.client
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

from common import INAT_DIR, INAT_MANIFEST

API = "https://api.inaturalist.org/v1/"
HEADERS = {"User-Agent": "ivy-finder-dataset/0.1"}
LICENSES = ["cc0", "cc-by", "cc-by-nc", "cc-by-sa", "cc-by-nc-sa"]  # no "no derivatives"
API_PAUSE_S = 1.1  # iNaturalist asks for at most one request a second
# HTTPException covers a transfer cut off part-way, which urllib does not wrap.
NETWORK_ERRORS = (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError)
MAX_PER_OBSERVER = 30  # stops one prolific person dominating a class

# folder, scientific names, number of photos.
# "hedera" is sorted by hand afterwards; every other folder is a negative.
# A source with several names shares its count between them.
SOURCES = [
    ("hedera", ["Hedera"], 3000),
    ("wintercreeper", ["Euonymus fortunei"], 600),
    ("virginia_creeper", ["Parthenocissus quinquefolia"], 450),
    ("poison_ivy", ["Toxicodendron radicans"], 450),
    ("boston_ivy", ["Parthenocissus tricuspidata"], 250),
    ("bittersweet", ["Celastrus orbiculatus"], 250),
    ("grape", ["Vitis"], 200),
    ("honeysuckle", ["Lonicera japonica"], 250),
    ("periwinkle", ["Vinca minor"], 400),
    ("pachysandra", ["Pachysandra terminalis"], 300),
    ("ground_ivy", ["Glechoma hederacea"], 250),
    ("moss", ["Bryophyta"], 200),
    ("trees", ["Quercus", "Acer", "Fagus grandifolia", "Liriodendron tulipifera", "Prunus serotina"], 600),
    # Any other vascular plant, so the model sees ordinary greenery too.
    ("plants", ["Tracheophyta"], 800),
    # Mushrooms are mostly photographed on leaf litter and logs: woodland
    # floor without ivy.
    ("fungi", ["Fungi"], 300),
    # iNaturalist has no photos of plain pavement or walls, so animals stand in
    # for "not a plant": birds against sky, insects on walls, fish, shells.
    # build_dataset.py files this folder under no_vegetation.
    ("animals", ["Aves", "Insecta", "Arachnida", "Mollusca", "Actinopterygii", "Mammalia", "Reptilia"], 1000),
]

MANIFEST_FIELDS = [
    "file", "folder", "taxon", "observation_id", "photo_id",
    "observer", "license", "attribution", "observed_on",
]


def api_get(path, **params):
    url = API + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as response:
                return json.load(response)
        except NETWORK_ERRORS as error:
            if attempt == 3:
                raise
            print(f"  request failed ({error}); retrying")
            time.sleep(5 * (attempt + 1))
        finally:
            time.sleep(API_PAUSE_S)


def resolve_taxon(name):
    """Return the iNaturalist id of the taxon with exactly this scientific name."""
    results = api_get("taxa", q=name, per_page=30)["results"]
    # The same name can exist in two kingdoms (there is an obscure animal genus
    # called Hedera), so take the most observed match.
    matches = [taxon for taxon in results if taxon["name"].lower() == name.lower()]
    if not matches:
        raise SystemExit(f"Nothing named {name!r} found on iNaturalist")
    return max(matches, key=lambda taxon: taxon.get("observations_count", 0))["id"]


def read_manifest():
    if not INAT_MANIFEST.exists():
        return {}
    with INAT_MANIFEST.open(newline="", encoding="utf-8") as handle:
        return {row["photo_id"]: row for row in csv.DictReader(handle)}


def write_manifest(rows):
    INAT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with INAT_MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(sorted(rows.values(), key=lambda row: (row["folder"], int(row["photo_id"]))))


def pick_photo(observation):
    for photo in observation.get("photos", []):
        if photo.get("license_code") in LICENSES and not photo.get("hidden") and photo.get("url"):
            return photo
    return None


def find_photos(folder, taxon_ids, exclude_ids, wanted, have, args):
    """Collect up to `wanted` new photo records, cycling through the months."""
    seen_observations = {row["observation_id"] for row in have.values()}
    per_observer = {}
    for row in have.values():
        if row["folder"] == folder:
            per_observer[row["observer"]] = per_observer.get(row["observer"], 0) + 1

    per_page = min(200, max(10, math.ceil(wanted / 12)))
    exhausted = set()
    found = []
    page = 1
    # The API refuses to page past 10,000 results.
    while len(found) < wanted and len(exhausted) < 12 and page * per_page <= 10_000:
        for month in range(1, 13):
            if month in exhausted or len(found) >= wanted:
                continue
            params = dict(
                taxon_id=",".join(map(str, taxon_ids)),
                quality_grade="research",
                photos="true",
                photo_license=",".join(LICENSES),
                lat=args.lat, lng=args.lng, radius=args.radius_km,
                month=month, per_page=per_page, page=page,
                order_by="id", order="desc",
            )
            if exclude_ids:
                params["without_taxon_id"] = ",".join(map(str, exclude_ids))
            results = api_get("observations", **params)["results"]
            if len(results) < per_page:
                exhausted.add(month)
            for observation in results:
                if len(found) >= wanted:
                    break
                observation_id = str(observation["id"])
                observer = observation["user"]["login"]
                photo = pick_photo(observation)
                if (
                    photo is None
                    or observation_id in seen_observations
                    or per_observer.get(observer, 0) >= MAX_PER_OBSERVER
                ):
                    continue
                seen_observations.add(observation_id)
                per_observer[observer] = per_observer.get(observer, 0) + 1
                # The API lists the square thumbnail; "medium" is up to 500 px.
                url = photo["url"].replace("/square.", "/medium.")
                extension = url.rsplit(".", 1)[-1].split("?")[0].lower()
                found.append({
                    "url": url,
                    "file": f"{folder}/{photo['id']}.{extension}",
                    "folder": folder,
                    "taxon": (observation.get("taxon") or {}).get("name", ""),
                    "observation_id": observation_id,
                    "photo_id": str(photo["id"]),
                    "observer": observer,
                    "license": photo["license_code"],
                    "attribution": photo.get("attribution", ""),
                    "observed_on": observation.get("observed_on") or "",
                })
        page += 1
    return found


def download(record):
    target = INAT_DIR / record["file"]
    if target.exists() and target.stat().st_size > 0:
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(record["url"], headers=HEADERS), timeout=60) as response:
                data = response.read()
            # Written under a temporary name so an interrupted run never
            # leaves a half-finished file that looks complete.
            partial = target.with_name(target.name + ".part")
            partial.write_bytes(data)
            partial.replace(target)
            return True
        except NETWORK_ERRORS:
            time.sleep(2 * (attempt + 1))
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scale", type=float, default=1.0, help="multiply every photo count by this")
    parser.add_argument("--only", action="append", help="download just this folder (repeatable)")
    parser.add_argument("--lat", type=float, default=40.44, help="centre of the search area (default Pittsburgh)")
    parser.add_argument("--lng", type=float, default=-79.99)
    parser.add_argument("--radius-km", type=float, default=500)
    args = parser.parse_args()

    known = {folder for folder, _, _ in SOURCES}
    for folder in args.only or []:
        if folder not in known:
            raise SystemExit(f"Unknown folder {folder!r}. Choose from: {', '.join(sorted(known))}")

    print("Looking up species...")
    taxon_ids = {folder: [resolve_taxon(name) for name in names] for folder, names, _ in SOURCES}
    specific_ids = [i for folder, ids in taxon_ids.items() if folder not in ("plants", "fungi", "animals") for i in ids]

    manifest = read_manifest()
    for folder, _, count in SOURCES:
        if args.only and folder not in args.only:
            continue
        target = max(1, round(count * args.scale))
        have = sum(1 for row in manifest.values() if row["folder"] == folder)
        if have >= target:
            print(f"{folder}: already have {have} of {target}")
            continue

        print(f"{folder}: have {have}, finding {target - have} more...")
        exclude = specific_ids if folder == "plants" else []
        records = find_photos(folder, taxon_ids[folder], exclude, target - have, manifest, args)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(download, records))
        saved = 0
        for record, ok in zip(records, outcomes):
            if ok:
                manifest[record["photo_id"]] = {field: record[field] for field in MANIFEST_FIELDS}
                saved += 1
        write_manifest(manifest)
        note = "" if have + saved >= target else "  (fewer than requested are available)"
        print(f"{folder}: downloaded {saved}, now {have + saved} of {target}{note}")

    print(f"Done. {len(manifest)} photos listed in {INAT_MANIFEST}")


if __name__ == "__main__":
    main()
