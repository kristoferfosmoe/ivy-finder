"""Sort the downloaded ivy photos by hand into climbing, ground or reject.

    python ml/sort_photos.py

Opens a page in your browser showing 24 photos at a time. Every photo starts
as "ground"; click one to change it to "climbing", click again for "reject".
Press Enter to save the page and move on. Progress is saved after every page
in data/labels/hedera.csv, so you can stop and pick up later.

The server only listens on this computer.
"""

import argparse
import csv
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from common import HEDERA_LABELS, INAT_DIR

FOLDER = INAT_DIR / "hedera"
CHOICES = ["ground", "climbing", "reject"]
PAGE_SIZE = 24
CONTENT_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Sort ivy photos</title>
<style>
  body { margin: 0; font: 15px/1.4 system-ui, sans-serif; background: #111; color: #eee; }
  header { position: sticky; top: 0; z-index: 1; background: #111; padding: 10px 16px; border-bottom: 1px solid #444; }
  header p { margin: 4px 0; }
  .rules span { margin-right: 18px; }
  button { font: inherit; padding: 8px 14px; margin-right: 8px; cursor: pointer; }
  #grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; padding: 8px; }
  @media (max-width: 1100px) { #grid { grid-template-columns: repeat(4, 1fr); } }
  .tile { position: relative; cursor: pointer; border: 5px solid #2563eb; background: #000; user-select: none; }
  .tile img { width: 100%; aspect-ratio: 1; object-fit: contain; display: block; }
  .tile b { position: absolute; left: 0; bottom: 0; padding: 2px 8px; background: #2563eb; color: #fff; }
  .tile.climbing { border-color: #ea580c; } .tile.climbing b { background: #ea580c; }
  .tile.reject { border-color: #555; } .tile.reject b { background: #555; } .tile.reject img { opacity: 0.3; }
</style></head><body>
<header>
  <p><strong id="progress"></strong></p>
  <p class="rules">
    <span><b>GROUND</b>: ivy leaves, no trunk or wall in view (includes close-ups)</span>
    <span><b>CLIMBING</b>: ivy on a trunk, wall or fence</span>
    <span><b>REJECT</b>: not clearly ivy, flowers or berries only, potted, drawing, too dark</span>
  </p>
  <p>
    <button id="prev">Back (B)</button><button id="next">Save and next (Enter)</button>
    Click a photo to change it. Keys 1 to 9 change the first nine.
  </p>
</header>
<div id="grid"></div>
<script>
const CHOICES = __CHOICES__;
let page = null, state = {};
async function load(n) {
  const response = await fetch('/api/page' + (n == null ? '' : '?n=' + n));
  page = await response.json();
  state = Object.fromEntries(page.items.map(item => [item.name, item.label || CHOICES[0]]));
  document.getElementById('progress').textContent = page.done
    ? 'All ' + page.total + ' photos sorted. You can close this tab and stop the script (Ctrl+C).'
    : 'Page ' + (page.n + 1) + ' of ' + page.pages + '.  Sorted ' + page.labeled + ' of ' + page.total +
      '  (climbing ' + page.counts.climbing + ', ground ' + page.counts.ground + ', reject ' + page.counts.reject + ')';
  const grid = document.getElementById('grid');
  grid.replaceChildren(...page.items.map(item => {
    const tile = document.createElement('div');
    tile.dataset.name = item.name;
    const img = document.createElement('img');
    img.src = '/img/' + encodeURIComponent(item.name);
    tile.append(img, document.createElement('b'));
    tile.addEventListener('click', () => cycle(tile));
    paint(tile);
    return tile;
  }));
  window.scrollTo(0, 0);
}
function paint(tile) {
  const label = state[tile.dataset.name];
  tile.className = 'tile ' + label;
  tile.querySelector('b').textContent = label.toUpperCase();
}
function cycle(tile) {
  const name = tile.dataset.name;
  state[name] = CHOICES[(CHOICES.indexOf(state[name]) + 1) % CHOICES.length];
  paint(tile);
}
async function save(step) {
  if (!page || page.done && step > 0) return;
  // Going back from a page you have not finished must not mark it as sorted.
  const reviewed = page.items.some(item => item.label);
  if (page.items.length && (step > 0 || reviewed)) {
    const response = await fetch('/api/labels', { method: 'POST', body: JSON.stringify(state) });
    if (!response.ok) { alert('Could not save this page. Is the script still running?'); return; }
  }
  await load(Math.max(0, page.n + step));
}
document.getElementById('next').addEventListener('click', () => save(1));
document.getElementById('prev').addEventListener('click', () => save(-1));
document.addEventListener('keydown', event => {
  if (event.key === 'Enter') { event.preventDefault(); save(1); }
  else if (event.key.toLowerCase() === 'b') save(-1);
  else if (/^[1-9]$/.test(event.key)) {
    const tile = document.getElementById('grid').children[Number(event.key) - 1];
    if (tile) cycle(tile);
  }
});
load();
</script></body></html>
"""


class Sorter:
    def __init__(self):
        self.names = sorted(path.name for path in FOLDER.iterdir() if path.suffix[1:].lower() in CONTENT_TYPES)
        self.labels = {}
        self.lock = threading.Lock()
        if HEDERA_LABELS.exists():
            with HEDERA_LABELS.open(newline="", encoding="utf-8") as handle:
                known = set(self.names)
                self.labels = {row["file"]: row["label"] for row in csv.DictReader(handle) if row["file"] in known}

    @property
    def pages(self):
        return max(1, -(-len(self.names) // PAGE_SIZE))

    def first_unsorted_page(self):
        for index, name in enumerate(self.names):
            if name not in self.labels:
                return index // PAGE_SIZE
        return self.pages  # one past the end: everything is sorted

    def page(self, n):
        if n is None:
            n = self.first_unsorted_page()
        n = max(0, min(n, self.pages))
        names = self.names[n * PAGE_SIZE:(n + 1) * PAGE_SIZE]
        counts = {choice: 0 for choice in CHOICES}
        for label in self.labels.values():
            counts[label] += 1
        return {
            "n": n, "pages": self.pages, "total": len(self.names), "labeled": len(self.labels),
            "counts": counts, "done": not names,
            "items": [{"name": name, "label": self.labels.get(name)} for name in names],
        }

    def save(self, updates):
        known = set(self.names)
        with self.lock:
            for name, label in updates.items():
                if name in known and label in CHOICES:
                    self.labels[name] = label
            HEDERA_LABELS.parent.mkdir(parents=True, exist_ok=True)
            partial = HEDERA_LABELS.with_name(HEDERA_LABELS.name + ".part")
            with partial.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["file", "label"])
                writer.writerows(sorted(self.labels.items()))
            partial.replace(HEDERA_LABELS)


def make_handler(sorter):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # keep the terminal quiet

        def send(self, status, content_type, body):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                self.send(200, "text/html; charset=utf-8", PAGE.replace("__CHOICES__", json.dumps(CHOICES)).encode())
            elif url.path == "/api/page":
                n = parse_qs(url.query).get("n")
                self.send(200, "application/json", json.dumps(sorter.page(int(n[0]) if n else None)).encode())
            elif url.path.startswith("/img/"):
                name = unquote(url.path[len("/img/"):])
                # Only files from the listing are served, never arbitrary paths.
                if name not in sorter.names:
                    self.send(404, "text/plain", b"not found")
                    return
                self.send(200, CONTENT_TYPES[name.rsplit(".", 1)[-1].lower()], (FOLDER / name).read_bytes())
            else:
                self.send(404, "text/plain", b"not found")

        def do_POST(self):
            if self.path != "/api/labels":
                self.send(404, "text/plain", b"not found")
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            sorter.save(json.loads(body))
            self.send(200, "application/json", b"{}")

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    args = parser.parse_args()

    if not FOLDER.is_dir():
        raise SystemExit(f"{FOLDER} does not exist. Run download_inat.py first.")
    sorter = Sorter()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(sorter))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"{len(sorter.names)} photos, {len(sorter.labels)} already sorted.")
    print(f"Open {url} (Ctrl+C here to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\nStopped. Labels are in {HEDERA_LABELS}")


if __name__ == "__main__":
    main()
