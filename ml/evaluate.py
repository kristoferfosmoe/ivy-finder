"""Score a trained model and write a report of what it gets wrong.

    python ml/evaluate.py --name v1

train.py runs this automatically. Run it by hand to re-score an existing
model after the dataset has changed.

The phone raises an alert when the ivy score (climbing plus ground) passes a
threshold. The threshold is chosen on the validation photos as the highest
value that still catches 90% of ivy, and is then applied unchanged to the
test photos.
"""

import argparse
import html
import json
import os

import keras
import numpy as np

from common import CLASSES, DATASET_DIR, IVY_CLASSES, RUNS_DIR
from data import make_dataset, read_split

TARGET_RECALL = 0.90
THRESHOLDS = [round(0.05 * step, 2) for step in range(1, 20)]
GALLERY_SIZE = 40
IVY_INDEXES = [CLASSES.index(label) for label in IVY_CLASSES]


def predict(model, rows):
    """Return (class probabilities, ivy score, true class index, is ivy)."""
    probabilities = model.predict(make_dataset(rows, training=False), verbose=0)
    truth = np.array([CLASSES.index(row["label"]) for row in rows])
    return probabilities, probabilities[:, IVY_INDEXES].sum(axis=1), truth, np.isin(truth, IVY_INDEXES)


def precision_recall(score, is_ivy, threshold):
    alert = score >= threshold
    caught = int((alert & is_ivy).sum())
    precision = caught / alert.sum() if alert.sum() else 1.0
    recall = caught / is_ivy.sum() if is_ivy.sum() else 0.0
    return float(precision), float(recall)


def choose_threshold(score, is_ivy):
    sweep = [(threshold, *precision_recall(score, is_ivy, threshold)) for threshold in THRESHOLDS]
    good = [row for row in sweep if row[2] >= TARGET_RECALL]
    if good:
        return good[-1][0], sweep  # the highest threshold that still catches enough ivy
    # Nothing reaches the target: fall back to the best balance of the two.
    best = max(sweep, key=lambda row: 2 * row[1] * row[2] / (row[1] + row[2]) if row[1] + row[2] else 0)
    return best[0], sweep


def summarise(rows, probabilities, score, truth, is_ivy, threshold):
    predicted = probabilities.argmax(axis=1)
    alert = score >= threshold
    precision, recall = precision_recall(score, is_ivy, threshold)
    summary = {
        "photos": len(rows),
        "accuracy": float((predicted == truth).mean()),
        "ivy_precision": precision,
        "ivy_recall": recall,
        "confusion": [[int(((truth == t) & (predicted == p)).sum()) for p in range(len(CLASSES))] for t in range(len(CLASSES))],
        "alert_rate": {},
    }
    # How often each class raises an alert: recall for ivy, false alarms otherwise.
    for index, label in enumerate(CLASSES):
        mask = truth == index
        if mask.any():
            summary["alert_rate"][label] = {"photos": int(mask.sum()), "rate": float(alert[mask].mean())}
    # False alarms broken down by kind of photo (species folder or field tag).
    kinds = {}
    for row, alerted, ivy in zip(rows, alert, is_ivy):
        if not ivy:
            entry = kinds.setdefault(f"{row['source']}: {row['detail']}", [0, 0])
            entry[0] += 1
            entry[1] += int(alerted)
    summary["false_alarms_by_kind"] = {kind: {"photos": n, "alerts": a} for kind, (n, a) in sorted(kinds.items())}
    return summary


# ---------- HTML report ----------

def percent(value):
    return f"{100 * value:.0f}%"


def table(header, body):
    cells = lambda row, tag: "".join(f"<{tag}>{html.escape(str(cell))}</{tag}>" for cell in row)
    return "<table><tr>" + cells(header, "th") + "</tr>" + "".join(f"<tr>{cells(row, 'td')}</tr>" for row in body) + "</table>"


def gallery(title, rows, score, order, run_dir):
    if not len(order):
        return f"<h3>{title}</h3><p>None.</p>"
    tiles = []
    for index in order[:GALLERY_SIZE]:
        row = rows[index]
        source = os.path.relpath(DATASET_DIR / row["file"], run_dir).replace(os.sep, "/")
        caption = f"{row['label']} ({row['source']}: {row['detail']}), ivy score {score[index]:.2f}"
        tiles.append(f'<figure><a href="{html.escape(source)}"><img loading="lazy" src="{html.escape(source)}"></a>'
                     f"<figcaption>{html.escape(caption)}</figcaption></figure>")
    return f"<h3>{title}</h3><div class='gallery'>{''.join(tiles)}</div>"


def section(name, rows, score, is_ivy, threshold, summary, run_dir):
    parts = [f"<h2>{name}: {summary['photos']} photos</h2>"]
    parts.append(f"<p>At the alert threshold of {threshold:.2f}: catches <b>{percent(summary['ivy_recall'])}</b> of ivy photos; "
                 f"<b>{percent(summary['ivy_precision'])}</b> of alerts are really ivy. "
                 f"Picks the exact class correctly {percent(summary['accuracy'])} of the time.</p>")
    parts.append("<h3>How often each class raises an alert</h3>")
    parts.append(table(["Class", "Photos", "Alerts"], [[label, entry["photos"], percent(entry["rate"])] for label, entry in summary["alert_rate"].items()]))
    parts.append("<h3>False alarms by kind of photo</h3>")
    parts.append(table(["Kind", "Photos", "False alarms"], [
        [kind, entry["photos"], f"{entry['alerts']} ({percent(entry['alerts'] / entry['photos'])})"]
        for kind, entry in summary["false_alarms_by_kind"].items()
    ]))
    parts.append("<h3>Confusion table (rows: truth, columns: model's top pick)</h3>")
    parts.append(table([""] + CLASSES, [[CLASSES[t]] + summary["confusion"][t] for t in range(len(CLASSES))]))
    missed = [i for i in np.argsort(score) if is_ivy[i] and score[i] < threshold]
    alarms = [i for i in np.argsort(-score) if not is_ivy[i] and score[i] >= threshold]
    parts.append(gallery(f"Missed ivy ({len(missed)}), worst first", rows, score, missed, run_dir))
    parts.append(gallery(f"False alarms ({len(alarms)}), worst first", rows, score, alarms, run_dir))
    return "".join(parts)


STYLE = """
body { font: 15px/1.5 system-ui, sans-serif; max-width: 1100px; margin: 24px auto; padding: 0 16px; color: #111; }
table { border-collapse: collapse; margin: 8px 0 16px; }
th, td { border: 1px solid #ccc; padding: 4px 10px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 8px; }
figure { margin: 0; } img { width: 100%; aspect-ratio: 1; object-fit: cover; }
figcaption { font-size: 12px; color: #444; }
"""


def evaluate_model(model, run_dir):
    """Score on validation and test photos, write report.html, return a summary."""
    val_rows, test_rows = read_split("val"), read_split("test")
    probabilities, score, truth, is_ivy = predict(model, val_rows)
    threshold, sweep = choose_threshold(score, is_ivy)

    scores = {"val": summarise(val_rows, probabilities, score, truth, is_ivy, threshold)}
    body = [f"<h1>Model report: {html.escape(run_dir.name)}</h1>"]
    if not test_rows:
        body.append("<p><b>No field test photos yet.</b> The validation figures below are mostly downloaded photos, "
                    "which are easier than real video frames. Treat them as an upper bound.</p>")
    else:
        t_prob, t_score, t_truth, t_ivy = predict(model, test_rows)
        scores["test"] = summarise(test_rows, t_prob, t_score, t_truth, t_ivy, threshold)
        body.append("<p>The <b>field test</b> section is the one that predicts how the phone app will behave: "
                    "your own photos, from places the model never trained on.</p>")
        body.append(section("Field test", test_rows, t_score, t_ivy, threshold, scores["test"], run_dir))
    body.append(section("Validation", val_rows, score, is_ivy, threshold, scores["val"], run_dir))
    body.append("<h2>Threshold choices (validation)</h2>")
    body.append(table(["Threshold", "Alerts that are ivy", "Ivy caught"], [[f"{t:.2f}", percent(p), percent(r)] for t, p, r in sweep]))

    (run_dir / "report.html").write_text(
        f"<!doctype html><meta charset='utf-8'><title>Model report</title><style>{STYLE}</style>{''.join(body)}",
        encoding="utf-8",
    )
    (run_dir / "scores.json").write_text(json.dumps({"threshold": threshold, "scores": scores}, indent=1))

    for name, summary in scores.items():
        print(f"  {name:5} {summary['photos']:5} photos: catches {percent(summary['ivy_recall'])} of ivy, "
              f"{percent(summary['ivy_precision'])} of alerts are ivy (threshold {threshold:.2f})")
    return {"threshold": threshold, "scores": scores}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="model version, for example v1")
    args = parser.parse_args()
    run_dir = RUNS_DIR / args.name
    evaluate_model(keras.saving.load_model(run_dir / "model.keras"), run_dir)
    print(f"Report: {run_dir / 'report.html'}")


if __name__ == "__main__":
    main()
