"""Convert a Keras image classifier into the TensorFlow.js format the site loads.

Two uses:

  # Stock ImageNet MobileNetV3-Small, for the device speed test in spike/
  python ml/export_tfjs.py --stock --out spike/model

  # A trained ivy model saved with model.save("ivy.keras")
  python ml/export_tfjs.py --model ivy.keras --out app/model/v1

Weights are stored as float16, which halves the download. Scores shift by
about 0.002 compared with Keras; the ranking of classes is unchanged.
"""

import argparse
import base64
import json
import os
import sys
import tempfile
import types
from pathlib import Path

# Must be set before TensorFlow loads. With oneDNN on (the default on x86
# Linux, including Colab), TensorFlow's graph optimizer merges each convolution
# with its hard-swish activation into a "_FusedHardSwish" op that the TF.js
# WebGL backend cannot run.
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"

import keras  # noqa: E402


def stub_unused_converter_dependencies():
    """Stand in empty modules for packages tensorflowjs imports but never uses here.

    The converter imports these on load for decision-forest, TF-Hub and JAX
    models. Their builds lag behind TensorFlow releases and fail to import, so
    installing them is not an option.
    """
    for name in ("tensorflow_decision_forests", "tensorflow_hub", "jax", "jax.experimental", "jax.experimental.jax2tf"):
        module = sys.modules.setdefault(name, types.ModuleType(name))
        parent, _, child = name.rpartition(".")
        if parent:
            setattr(sys.modules[parent], child, module)


def check_browser_compatible(model_json):
    """Fail loudly if the graph still contains an activation TF.js cannot run."""
    graph = json.loads(model_json.read_text())["modelTopology"]["node"]
    bad = set()
    for node in graph:
        for encoded in node.get("attr", {}).get("fused_ops", {}).get("list", {}).get("s", []):
            name = base64.b64decode(encoded).decode()
            if name.startswith("_Fused"):
                bad.add(name)
    if bad:
        sys.exit(f"Export contains ops the TF.js WebGL backend cannot run: {sorted(bad)}")


def load_model(args):
    if args.stock:
        # include_preprocessing=True (the default) bakes pixel scaling into the
        # model, so the browser feeds it raw 0-255 RGB values.
        return keras.applications.MobileNetV3Small(input_shape=(224, 224, 3), weights="imagenet")
    return keras.saving.load_model(args.model)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--stock", action="store_true", help="export ImageNet MobileNetV3-Small")
    source.add_argument("--model", type=Path, help="path to a saved .keras model")
    parser.add_argument("--out", type=Path, required=True, help="output directory for model.json and weights")
    args = parser.parse_args()

    model = load_model(args)

    stub_unused_converter_dependencies()

    from tensorflowjs.converters import tf_saved_model_conversion_v2 as converter
    from tensorflowjs import quantization

    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as saved_model_dir:
        model.export(saved_model_dir)
        converter.convert_tf_saved_model(
            saved_model_dir,
            str(args.out),
            quantization_dtype_map={quantization.QUANTIZATION_DTYPE_FLOAT16: "*"},
        )

    check_browser_compatible(args.out / "model.json")

    size_mb = sum(f.stat().st_size for f in args.out.iterdir()) / 1e6
    print(f"Wrote {args.out} ({size_mb:.1f} MB), input {model.input_shape}, output {model.output_shape}")


if __name__ == "__main__":
    main()
