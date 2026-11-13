"""Copy the photos taken with the capture app from Supabase to this computer.

    python ml/pull_field_photos.py you@example.com

Asks for your Ivy Finder password (the one you sign in to the app with), then
downloads every observation's photo into data/field/ and writes
data/field/manifest.csv. Already downloaded photos are skipped, so rerun it
whenever you have taken more.

The project address and public key are read from config.js.
"""

import argparse
import csv
import getpass
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from common import FIELD_DIR, FIELD_MANIFEST, REPO

PAGE_SIZE = 1000

# The capture app's tags, mapped to the model's classes. Ivy growing both on
# the ground and up a trunk counts as climbing: a trunk is in the frame.
NEGATIVE_SUBJECTS = {
    "lookalike": "other_vegetation",
    "trunk_no_ivy": "other_vegetation",
    "other_vegetation": "other_vegetation",
    "no_vegetation": "no_vegetation",
}

MANIFEST_FIELDS = ["file", "label", "group", "observation_id", "subject", "growth_form", "captured_at", "lat", "lon"]


def read_config():
    text = (REPO / "config.js").read_text(encoding="utf-8")
    url = re.search(r"supabaseUrl:\s*'([^']+)'", text)
    key = re.search(r"supabaseAnonKey:\s*'([^']+)'", text)
    if not url or not key or "YOUR-PROJECT" in url.group(1):
        raise SystemExit("Set supabaseUrl and supabaseAnonKey in config.js first.")
    return url.group(1).rstrip("/"), key.group(1)


def request(url, key, token=None, body=None):
    headers = {"apikey": key, "Authorization": f"Bearer {token or key}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        raise SystemExit(f"Supabase refused the request ({error.code}): {detail}") from None


def label_for(row):
    if row["subject"] == "ivy":
        return "ivy_ground" if row["growth_form"] == "ground" else "ivy_climbing"
    return NEGATIVE_SUBJECTS[row["subject"]]


def group_for(row):
    """Photos in the same group stay in the same train/validation/test split.

    Photos of one tree are near-duplicates, so everything within the same cell
    of roughly 50 m is kept together. Photos without a location are grouped by
    the hour they were taken.
    """
    if row["lat"] is not None:
        return f"cell_{round(row['lat'] / 0.0005)}_{round(row['lon'] / 0.0005)}"
    return "time_" + row["captured_at"][:13]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email", help="the email you sign in to Ivy Finder with")
    args = parser.parse_args()

    base, key = read_config()
    password = os.environ.get("IVY_PASSWORD") or getpass.getpass("Ivy Finder password: ")
    session = json.loads(request(
        f"{base}/auth/v1/token?grant_type=password", key,
        body={"email": args.email, "password": password},
    ))
    token = session["access_token"]

    rows = []
    while True:
        query = urllib.parse.urlencode({"select": "*", "order": "captured_at.asc,id.asc", "limit": PAGE_SIZE, "offset": len(rows)})
        page = json.loads(request(f"{base}/rest/v1/observations?{query}", key, token))
        # Stop on an empty page, not a short one: a project can be set to
        # return fewer rows per request than asked for.
        if not page:
            break
        rows.extend(page)
    print(f"{len(rows)} observations in Supabase")

    photos = FIELD_DIR / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    manifest = []
    downloaded = 0
    for row in rows:
        target = photos / f"{row['id']}.jpg"
        if not target.exists() or target.stat().st_size == 0:
            path = urllib.parse.quote(row["photo_path"])
            data = request(f"{base}/storage/v1/object/photos/{path}", key, token)
            partial = target.with_name(target.name + ".part")
            partial.write_bytes(data)
            partial.replace(target)
            downloaded += 1
        manifest.append({
            "file": f"photos/{target.name}",
            "label": label_for(row),
            "group": group_for(row),
            "observation_id": row["id"],
            "subject": row["subject"],
            "growth_form": row["growth_form"] or "",
            "captured_at": row["captured_at"],
            "lat": "" if row["lat"] is None else row["lat"],
            "lon": "" if row["lon"] is None else row["lon"],
        })

    with FIELD_MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(manifest)

    counts = {}
    for entry in manifest:
        counts[entry["label"]] = counts.get(entry["label"], 0) + 1
    print(f"Downloaded {downloaded} new photos. Totals by class:")
    for label, count in sorted(counts.items()):
        print(f"  {label:18} {count}")
    print(f"  in {len({entry['group'] for entry in manifest})} separate places")


if __name__ == "__main__":
    main()
