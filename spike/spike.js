// Measures how fast this device classifies camera frames with MobileNetV3-Small,
// the architecture the ivy model will use. Weights are stock ImageNet ones, so
// the labels only serve as a sanity check that frames reach the model intact.

const tf = window.tf;
const $ = (id) => document.getElementById(id);

const INPUT_SIZE = 224;
const WINDOW = 50; // inferences in the rolling statistics

const video = $('video');
const report = { device: navigator.userAgent };
const times = [];

$('start').addEventListener('click', run);
$('copy').addEventListener('click', async () => {
  await navigator.clipboard.writeText($('results').textContent);
  $('copy').textContent = 'Copied';
});

async function run() {
  $('start').disabled = true;
  $('results').hidden = false;
  try {
    show('Loading model…');
    await tf.ready();
    report.backend = tf.getBackend();
    if (report.backend === 'webgl') report.webglVersion = tf.env().getNumber('WEBGL_VERSION');

    let started = performance.now();
    const [model, labels] = await Promise.all([
      tf.loadGraphModel('model/model.json'),
      fetch('labels.json').then((response) => response.json()),
    ]);
    report.modelLoadMs = Math.round(performance.now() - started);

    show('Starting camera…');
    video.srcObject = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1440 }, height: { ideal: 1080 } },
    });
    video.hidden = false;
    await video.play();
    report.camera = `${video.videoWidth}x${video.videoHeight}`;

    // The first inference compiles shaders, so it is reported separately.
    started = performance.now();
    await classify(model);
    report.firstInferenceMs = Math.round(performance.now() - started);

    $('start').hidden = true;
    $('rate').hidden = false;
    $('copy').hidden = false;

    while (video.srcObject) {
      started = performance.now();
      const scores = await classify(model);
      times.push(performance.now() - started);
      if (times.length > WINDOW) times.shift();
      report.inferences = (report.inferences ?? 0) + 1;
      render(scores, labels);
      // Yield so the page can paint and respond to taps.
      await new Promise(requestAnimationFrame);
    }
  } catch (error) {
    show(`Failed: ${error.message}`);
  }
}

/** Centre-crops the current frame to a square, resizes it and runs the model. */
async function classify(model) {
  const output = tf.tidy(() => {
    const frame = tf.browser.fromPixels(video);
    const [height, width] = frame.shape;
    const side = Math.min(height, width);
    const top = Math.floor((height - side) / 2);
    const left = Math.floor((width - side) / 2);
    const square = frame.slice([top, left, 0], [side, side, 3]);
    // The exported model scales pixels itself and expects raw 0-255 values.
    const input = tf.image.resizeBilinear(square, [INPUT_SIZE, INPUT_SIZE]).toFloat().expandDims(0);
    return model.predict(input);
  });
  const scores = await output.data(); // waits for the GPU to finish
  output.dispose();
  return scores;
}

function render(scores, labels) {
  const sorted = [...times].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const p90 = sorted[Math.floor(sorted.length * 0.9)];
  report.medianMs = Math.round(median);
  report.p90Ms = Math.round(p90);
  report.perSecond = Math.round((1000 / median) * 10) / 10;
  $('rate').textContent = `${report.perSecond} per second`;

  const top = Array.from(scores, (score, index) => [score, index])
    .sort((a, b) => b[0] - a[0])
    .slice(0, 3)
    .map(([score, index]) => `${labels[index]} ${Math.round(score * 100)}%`);
  $('labels').textContent = top.join(' · ');
  show();
}

function show(note) {
  const lines = Object.entries(report).map(([key, value]) => `${key}: ${value}`);
  if (note) lines.push(note);
  $('results').textContent = lines.join('\n');
}
