"""Train the ivy classifier, score it, and export it for the phone app.

    python ml/train.py --name v1

Reads data/dataset (made by build_dataset.py). Writes:

  ml/runs/v1/model.keras    the trained model
  ml/runs/v1/report.html    scores and the photos it got wrong
  app/model/v1/             the browser model and meta.json, ready to commit

Training runs in two stages. First only a new final layer is trained on top
of a network that already recognises general images. Then the whole network
is fine-tuned gently. Takes 20 to 30 minutes on a four-core computer, no GPU
needed.
"""

import argparse
import json
import subprocess
import sys
from datetime import date

import keras

from common import APP_MODEL_DIR, CLASSES, INPUT_SIZE, REPO, RUNS_DIR
from data import make_dataset, read_split
from evaluate import evaluate_model

def build_model():
    # The backbone scales pixels itself, so inputs are raw 0-255 RGB.
    backbone = keras.applications.MobileNetV3Small(
        input_shape=(INPUT_SIZE, INPUT_SIZE, 3), include_top=False, weights="imagenet", pooling="avg",
    )
    inputs = keras.Input((INPUT_SIZE, INPUT_SIZE, 3))
    features = backbone(inputs)
    features = keras.layers.Dropout(0.2)(features)
    outputs = keras.layers.Dense(len(CLASSES), activation="softmax")(features)
    return keras.Model(inputs, outputs), backbone


def unfreeze(backbone):
    """Make the backbone trainable, except its batch-normalisation layers.

    Those layers hold running statistics from the original training. Left
    trainable, they switch to per-batch statistics during fitting, and the
    model then scores far worse on anything outside the training loop
    (validation accuracy fell from 73% to 53% in testing). Marking the layer
    itself as not trainable is what keeps it in inference mode; passing
    training=False when calling the backbone does not.
    """
    backbone.trainable = True
    for layer in backbone.layers:
        if isinstance(layer, keras.layers.BatchNormalization):
            layer.trainable = False


def fit(model, train, val, epochs, learning_rate, steps):
    schedule = keras.optimizers.schedules.CosineDecay(learning_rate, max(1, epochs * steps))
    model.compile(
        optimizer=keras.optimizers.Adam(schedule),
        loss=keras.losses.CategoricalCrossentropy(label_smoothing=0.1),
        metrics=["accuracy"],
    )
    stop = keras.callbacks.EarlyStopping(monitor="val_loss", patience=4, restore_best_weights=True)
    return model.fit(train, validation_data=val, epochs=epochs, callbacks=[stop], verbose=2).history


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="model version, for example v1")
    parser.add_argument("--head-epochs", type=int, default=6, help="epochs training only the new final layer")
    parser.add_argument("--finetune-epochs", type=int, default=16, help="epochs fine-tuning the whole network")
    parser.add_argument("--no-export", action="store_true", help="skip writing the browser model")
    args = parser.parse_args()

    train_rows, val_rows, test_rows = read_split("train"), read_split("val"), read_split("test")
    if not train_rows or not val_rows:
        raise SystemExit("data/dataset has no training or validation photos. Run build_dataset.py first.")
    print(f"{len(train_rows)} training, {len(val_rows)} validation, {len(test_rows)} test photos")

    run_dir = RUNS_DIR / args.name
    run_dir.mkdir(parents=True, exist_ok=True)
    train, val = make_dataset(train_rows, True), make_dataset(val_rows, False)
    steps = len(train)

    model, backbone = build_model()
    print("\nStage 1: training the final layer")
    backbone.trainable = False
    history = {"head": fit(model, train, val, args.head_epochs, 1e-3, steps)}
    head_weights = model.get_weights()
    print("\nStage 2: fine-tuning the whole network")
    unfreeze(backbone)
    history["finetune"] = fit(model, train, val, args.finetune_epochs, 1e-4, steps)
    if min(history["finetune"]["val_loss"]) > min(history["head"]["val_loss"]):
        print("Fine-tuning did not improve on stage 1; keeping the stage 1 model.")
        model.set_weights(head_weights)

    model.save(run_dir / "model.keras")
    (run_dir / "history.json").write_text(json.dumps(history, indent=1))

    print("\nScoring")
    results = evaluate_model(model, run_dir)

    meta = {
        "version": args.name,
        "trained_on": date.today().isoformat(),
        "classes": CLASSES,
        "input_size": INPUT_SIZE,
        "ivy_threshold": results["threshold"],
        "photos": {"train": len(train_rows), "val": len(val_rows), "test": len(test_rows)},
        "scores": results["scores"],
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=1))

    if not args.no_export:
        out_dir = APP_MODEL_DIR / args.name
        # A separate process, because exporting needs a TensorFlow setting
        # that slows training down (see export_tfjs.py).
        subprocess.run(
            [sys.executable, str(REPO / "ml" / "export_tfjs.py"), "--model", str(run_dir / "model.keras"), "--out", str(out_dir)],
            check=True,
        )
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=1))
        print(f"\nBrowser model written to {out_dir}")
    print(f"Report: {run_dir / 'report.html'}")


if __name__ == "__main__":
    main()
