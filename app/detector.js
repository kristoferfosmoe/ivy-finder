// Live ivy detection: classifies camera frames with the trained model and
// reports a smoothed ivy score.

const tf = window.tf;

// Training photos are stored 320 px on the short side and then resized to the
// model's input, so frames go through the same two steps here.
const PREP_SIZE = 320;
const MIN_GAP_MS = 200;      // at most five classifications a second
const NEW_FRAME_WEIGHT = 0.4; // smoothing: how much the newest frame counts
const RELEASE_MARGIN = 0.1;   // the alert clears this far below the threshold, to stop flicker

/**
 * Loads model/<version>/ and returns a detector.
 *
 *   detector.start(video, onUpdate)  begin classifying; onUpdate(state) per frame
 *   detector.stop()
 *   detector.state                   latest state, or null before the first frame
 *
 * state: { version, ivyScore, alert, ivyClass, topClass }
 */
export async function loadDetector(version) {
  const base = `model/${version}/`;
  const metaResponse = await fetch(base + 'meta.json');
  if (!metaResponse.ok) throw new Error(`model ${version} not found`);
  const meta = await metaResponse.json();
  await tf.ready();
  const model = await tf.loadGraphModel(base + 'model.json');

  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = PREP_SIZE;
  const context = canvas.getContext('2d');
  context.imageSmoothingQuality = 'high';

  const climbing = meta.classes.indexOf('ivy_climbing');
  const ground = meta.classes.indexOf('ivy_ground');
  const threshold = meta.ivy_threshold;

  // Each start gets a new run number. A loop from an earlier start sees the
  // number has moved on and exits, so stop-then-start never leaves two loops.
  let run = 0;
  let running = false;
  let smoothed = null;
  let alert = false;

  async function classify(video) {
    // Centre square of the frame, the same region the dashed guide marks.
    const side = Math.min(video.videoWidth, video.videoHeight);
    context.drawImage(
      video,
      (video.videoWidth - side) / 2, (video.videoHeight - side) / 2, side, side,
      0, 0, PREP_SIZE, PREP_SIZE,
    );
    const output = tf.tidy(() => {
      const pixels = tf.browser.fromPixels(canvas);
      // The model scales pixels itself and expects raw 0-255 values.
      // Half-pixel centres (the last argument) match how TensorFlow resized
      // the training photos.
      const input = tf.image
        .resizeBilinear(pixels, [meta.input_size, meta.input_size], false, true)
        .toFloat()
        .expandDims(0);
      return model.predict(input);
    });
    const scores = await output.data();
    output.dispose();
    return scores;
  }

  function update(scores) {
    smoothed = smoothed
      ? smoothed.map((old, i) => old + NEW_FRAME_WEIGHT * (scores[i] - old))
      : Array.from(scores);
    const ivyScore = smoothed[climbing] + smoothed[ground];
    alert = alert ? ivyScore >= threshold - RELEASE_MARGIN : ivyScore >= threshold;
    detector.state = {
      version: meta.version,
      ivyScore,
      alert,
      ivyClass: smoothed[climbing] >= smoothed[ground] ? 'climbing' : 'ground',
      topClass: meta.classes[smoothed.indexOf(Math.max(...smoothed))],
    };
    return detector.state;
  }

  const detector = {
    threshold,
    state: null,

    async start(video, onUpdate) {
      if (running) return;
      running = true;
      const mine = ++run;
      while (running && run === mine) {
        const started = performance.now();
        if (video.readyState >= 2 && video.videoWidth) {
          const scores = await classify(video);
          if (!running || run !== mine) break; // stopped while classifying
          onUpdate(update(scores));
        }
        const wait = Math.max(0, MIN_GAP_MS - (performance.now() - started));
        await new Promise((resolve) => setTimeout(resolve, wait));
      }
    },

    stop() {
      running = false;
      // Forget the old scene so a stale alert isn't shown on return.
      smoothed = null;
      alert = false;
      detector.state = null;
    },
  };
  return detector;
}
