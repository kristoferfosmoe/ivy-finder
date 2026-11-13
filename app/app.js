import { db, BUCKET, requireLogin, signOut } from '../shared/client.js';
import * as queue from './queue.js';
import { loadDetector } from './detector.js';

const cfg = window.IVY_CONFIG;
const $ = (id) => document.getElementById(id);

const video = $('video');
const shutter = $('shutter');
const gpsLine = $('gps');
const messageLine = $('message');
const pendingButton = $('pending');

// A fix older than this is treated as missing, so a stale position from the
// last tree is never attached to a new observation.
const MAX_FIX_AGE_MS = 60_000;

const SETTINGS_KEY = 'ivy-finder.capture-settings';
const settings = loadSettings();
let user = null;
let fix = null;
let syncing = false;
let detector = null;

$('signout').addEventListener('click', signOut);
requireLogin(start);

function start(signedInUser) {
  user = signedInUser;
  bindControls();
  startCamera();
  watchLocation();
  refreshPending();
  sync();
  startDetector();

  shutter.addEventListener('click', capture);
  pendingButton.addEventListener('click', sync);
  window.addEventListener('online', sync);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') {
      detector?.stop();
      showDetection(null);
      return;
    }
    // iOS ends the camera track when the page is backgrounded.
    const track = video.srcObject?.getVideoTracks()[0];
    if (!track || track.readyState === 'ended') startCamera();
    sync();
    runDetector();
  });
  $('alert').addEventListener('click', applySuggestion);
}

// ---------- Capture settings ----------

function loadSettings() {
  const defaults = { subject: 'ivy', growth_form: 'climbing', trunk_height: null, mature: false, vines_cut: false };
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(SETTINGS_KEY)) };
  } catch {
    return defaults;
  }
}

function saveSettings() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Private browsing: settings just won't persist.
  }
}

function bindControls() {
  for (const group of document.querySelectorAll('.chips')) {
    const field = group.dataset.field;
    group.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      const value = button.dataset.value;
      // Trunk height is optional, so tapping the selected chip clears it.
      settings[field] = field === 'trunk_height' && settings[field] === value ? null : value;
      saveSettings();
      renderControls();
    });
  }
  for (const id of ['mature', 'vines_cut']) {
    $(id).addEventListener('change', (event) => {
      settings[id] = event.target.checked;
      saveSettings();
    });
  }
  renderControls();
}

function renderControls() {
  for (const group of document.querySelectorAll('.chips')) {
    for (const button of group.querySelectorAll('button')) {
      button.setAttribute('aria-pressed', String(settings[group.dataset.field] === button.dataset.value));
    }
  }
  const isIvy = settings.subject === 'ivy';
  $('ivy-fields').hidden = !isIvy;
  document.querySelector('[data-field="trunk_height"]').hidden = !isIvy || settings.growth_form === 'ground';
  $('mature').checked = settings.mature;
  $('vines_cut').checked = settings.vines_cut;
}

// ---------- Camera and location ----------

async function startCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      // 4:3 is the full sensor on most phones, so it gives the widest view.
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1440 }, height: { ideal: 1080 } },
    });
    video.srcObject = stream;
    await video.play();
    const portrait = video.videoHeight >= video.videoWidth;
    $('viewfinder').style.setProperty('--ratio', video.videoWidth / video.videoHeight);
    $('guide').classList.toggle('portrait', portrait);
    shutter.disabled = false;
  } catch (error) {
    shutter.disabled = true;
    say(`Camera unavailable: ${error.message}`, true);
  }
}

function watchLocation() {
  if (!navigator.geolocation) {
    gpsLine.textContent = 'This browser has no location support.';
    return;
  }
  navigator.geolocation.watchPosition(
    (position) => {
      fix = position;
      gpsLine.textContent = `GPS ±${Math.round(position.coords.accuracy)} m`;
    },
    (error) => {
      gpsLine.textContent = `No GPS: ${error.message}`;
    },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 30_000 },
  );
}

function currentFix() {
  return fix && Date.now() - fix.timestamp <= MAX_FIX_AGE_MS ? fix : null;
}

// ---------- Live detection ----------

async function startDetector() {
  const line = $('detector');
  if (!cfg.modelVersion) {
    line.textContent = 'Detector off: no model set in config.js.';
    return;
  }
  line.textContent = 'Loading detector…';
  try {
    detector = await loadDetector(cfg.modelVersion);
    $('meter-mark').style.left = `${detector.threshold * 100}%`;
    $('meter').hidden = false;
    line.textContent = `Detector ${cfg.modelVersion} running.`;
    runDetector();
  } catch (error) {
    line.textContent = `Detector unavailable: ${error.message}`;
  }
}

function runDetector() {
  if (!detector) return;
  detector.start(video, showDetection).catch((error) => {
    detector.stop();
    showDetection(null);
    $('detector').textContent = `Detector stopped: ${error.message}`;
  });
}

let wasAlerting = false;

function showDetection(state) {
  const alerting = Boolean(state?.alert);
  $('meter-fill').style.width = `${Math.round((state?.ivyScore ?? 0) * 100)}%`;
  $('viewfinder').classList.toggle('alerting', alerting);
  $('alert').hidden = !alerting;
  if (alerting) {
    $('alert').textContent = `Ivy likely: ${state.ivyClass}. Tap to tag.`;
    // A short buzz when ivy first comes into view (Android only; iOS has no vibration).
    if (!wasAlerting) navigator.vibrate?.(150);
  }
  wasAlerting = alerting;
}

// Tapping the alert sets the tags to what the model sees. It is never applied
// automatically, so a false alarm cannot silently mislabel a photo.
function applySuggestion() {
  const state = detector?.state;
  if (!state) return;
  settings.subject = 'ivy';
  settings.growth_form = state.ivyClass;
  saveSettings();
  renderControls();
}

// What the model thought at the moment of capture, stored with the photo so
// its mistakes can be found later and used for retraining.
function detectionFields(isIvy) {
  const state = detector?.state;
  if (!state) return {};
  return {
    model_version: state.version,
    model_class: state.topClass,
    model_score: Math.round(state.ivyScore * 1000) / 1000,
    // Only an alert asks the user a question; their tag is the answer.
    user_confirmed: state.alert ? isIvy : null,
  };
}

// ---------- Capture ----------

async function capture() {
  const position = currentFix();
  const isIvy = settings.subject === 'ivy';
  if (isIvy && !position) {
    say('No recent GPS fix. Ivy records need a location; wait for a fix and try again.', true);
    return;
  }

  shutter.disabled = true;
  try {
    const blob = await grabFrame();
    const id = crypto.randomUUID();
    const climbs = isIvy && settings.growth_form !== 'ground';
    const row = {
      id,
      captured_at: new Date().toISOString(),
      subject: settings.subject,
      growth_form: isIvy ? settings.growth_form : null,
      trunk_height: climbs ? settings.trunk_height : null,
      mature: isIvy && settings.mature,
      vines_cut: isIvy && settings.vines_cut,
      notes: $('notes').value.trim() || null,
      lat: position?.coords.latitude ?? null,
      lon: position?.coords.longitude ?? null,
      accuracy_m: position?.coords.accuracy ?? null,
      photo_path: `${user.id}/${id}.jpg`,
      ...detectionFields(isIvy),
    };
    await queue.add({ id, row, blob });
    $('notes').value = '';
    flash();
    say('Saved.');
    await refreshPending();
    sync();
  } catch (error) {
    say(`Could not save: ${error.message}`, true);
  } finally {
    shutter.disabled = false;
  }
}

function grabFrame() {
  const scale = Math.min(1, cfg.photoMaxSide / Math.max(video.videoWidth, video.videoHeight));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('empty camera frame'))), 'image/jpeg', 0.85);
  });
}

function flash() {
  const el = $('flash');
  el.classList.remove('on');
  void el.offsetWidth; // restart the animation
  el.classList.add('on');
}

// ---------- Upload ----------

async function sync() {
  if (syncing || !navigator.onLine) return;
  syncing = true;
  let uploaded = 0;
  let failed = 0;
  let lastError = null;
  try {
    // One bad item must not block the rest of the queue, so failures are
    // counted and the loop carries on.
    for (const item of await queue.all()) {
      try {
        await upload(item);
        await queue.remove(item.id);
        uploaded += 1;
      } catch (error) {
        failed += 1;
        lastError = error;
      }
      await refreshPending();
    }
  } catch (error) {
    failed += 1;
    lastError = error;
  } finally {
    syncing = false;
  }
  if (failed) {
    say(`Upload failed: ${lastError.message}. Photos stay on this phone until it works.`, true);
  } else if (uploaded) {
    say(uploaded === 1 ? 'Uploaded.' : `Uploaded ${uploaded} photos.`);
  }
}

// Both steps treat "already there" as success, so retrying after a half-finished
// upload is safe.
async function upload({ row, blob }) {
  const stored = await db.storage.from(BUCKET).upload(row.photo_path, blob, { contentType: 'image/jpeg' });
  if (stored.error && !isDuplicateUpload(stored.error)) throw stored.error;

  const inserted = await db.from('observations').insert(row);
  if (inserted.error && inserted.error.code !== '23505') throw inserted.error;
}

function isDuplicateUpload(error) {
  return String(error.statusCode ?? error.status) === '409' || /already exists/i.test(error.message ?? '');
}

async function refreshPending() {
  const waiting = await queue.count();
  pendingButton.hidden = waiting === 0;
  pendingButton.textContent = `${waiting} to upload`;
}

function say(text, isError = false) {
  messageLine.textContent = text;
  messageLine.classList.toggle('error', isError);
}
