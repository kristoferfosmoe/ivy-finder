"""Loading photos from data/dataset into TensorFlow, shared by train and evaluate."""

import csv

import keras
import numpy as np
import tensorflow as tf

from common import CLASSES, DATASET_DIR, DATASET_INDEX, INPUT_SIZE

BATCH = 32
FIELD_WEIGHT = 3.0  # field photos count this much more than downloaded ones
MAX_CLASS_WEIGHT = 5.0


def read_split(split):
    with DATASET_INDEX.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row["split"] == split]


def decode(path):
    return tf.io.decode_jpeg(tf.io.read_file(path), channels=3)


def centre_square(image):
    """What the phone does: take the centre square of the frame and resize it."""
    shape = tf.shape(image)
    side = tf.minimum(shape[0], shape[1])
    image = tf.image.crop_to_bounding_box(image, (shape[0] - side) // 2, (shape[1] - side) // 2, side, side)
    return tf.image.resize(image, [INPUT_SIZE, INPUT_SIZE])


def augment(image):
    """Random variations so the model does not memorise exact framing or lighting."""
    shape = tf.shape(image)
    short = tf.cast(tf.minimum(shape[0], shape[1]), tf.float32)
    side = tf.cast(short * tf.random.uniform([], 0.6, 1.0), tf.int32)
    image = tf.image.random_crop(image, tf.stack([side, side, 3]))
    image = tf.image.resize(image, [INPUT_SIZE, INPUT_SIZE])
    image = tf.image.random_flip_left_right(image)
    image = tf.image.random_brightness(image, 0.15 * 255)
    image = tf.image.random_contrast(image, 0.75, 1.3)
    image = tf.image.random_saturation(image, 0.75, 1.3)
    # A third of the time, soften the image the way a moving phone camera does.
    low = tf.random.uniform([], 96, 160, dtype=tf.int32)
    soft = tf.image.resize(tf.image.resize(image, tf.stack([low, low])), [INPUT_SIZE, INPUT_SIZE])
    image = tf.where(tf.random.uniform([]) < 0.33, soft, image)
    return tf.clip_by_value(image, 0.0, 255.0)


def sample_weights(rows):
    """Balance the classes and lean towards field photos."""
    counts = {label: sum(row["label"] == label for row in rows) for label in CLASSES}
    present = [label for label in CLASSES if counts[label]]
    weights = []
    for row in rows:
        balance = min(MAX_CLASS_WEIGHT, len(rows) / (len(present) * counts[row["label"]]))
        weights.append(balance * (FIELD_WEIGHT if row["source"] == "field" else 1.0))
    weights = np.array(weights, dtype="float32")
    return weights / weights.mean()


def make_dataset(rows, training):
    paths = [str(DATASET_DIR / row["file"]) for row in rows]
    labels = keras.utils.to_categorical([CLASSES.index(row["label"]) for row in rows], len(CLASSES))
    if training:
        dataset = tf.data.Dataset.from_tensor_slices((paths, labels, sample_weights(rows)))
        dataset = dataset.shuffle(len(rows), reshuffle_each_iteration=True)
        dataset = dataset.map(lambda p, y, w: (augment(decode(p)), y, w), num_parallel_calls=tf.data.AUTOTUNE)
    else:
        dataset = tf.data.Dataset.from_tensor_slices((paths, labels))
        dataset = dataset.map(lambda p, y: (centre_square(decode(p)), y), num_parallel_calls=tf.data.AUTOTUNE)
    return dataset.batch(BATCH).prefetch(tf.data.AUTOTUNE)
