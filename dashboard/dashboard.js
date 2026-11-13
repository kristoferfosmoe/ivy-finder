import { db, BUCKET, requireLogin, signOut } from '../shared/client.js';

const L = window.L;
const cfg = window.IVY_CONFIG;
const $ = (id) => document.getElementById(id);

const PAGE_SIZE = 1000; // Supabase returns at most this many rows per request
const STATUSES = ['reported', 'verified', 'treated', 'removed'];
const LABELS = {
  ivy: 'Ivy',
  lookalike: 'Look-alike',
  trunk_no_ivy: 'Trunk, no ivy',
  other_vegetation: 'Other plants',
  no_vegetation: 'No plants',
  climbing: 'Climbing',
  ground: 'Ground',
  both: 'Climbing and ground',
  base: 'Base only',
  mid_trunk: 'Mid-trunk',
  canopy: 'Into canopy',
};

let user = null;
let rows = [];
let map = null;
let markers = null;

$('signout').addEventListener('click', signOut);
requireLogin(start);

async function start(signedInUser) {
  user = signedInUser;
  map = L.map('map').setView(cfg.mapCenter, cfg.mapZoom);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  markers = L.layerGroup().addTo(map);

  for (const id of ['filter-subject', 'filter-growth', 'filter-status']) {
    // Refit on every filter change so the matching pins are never off-screen.
    $(id).addEventListener('change', () => render(true));
  }
  $('export-csv').addEventListener('click', exportCsv);
  $('export-geojson').addEventListener('click', exportGeoJson);

  try {
    rows = await loadAll();
    render(true);
  } catch (error) {
    $('summary').textContent = `Could not load observations: ${error.message}`;
    $('summary').classList.add('error');
  }
}

async function loadAll() {
  const all = [];
  for (let from = 0; ; from += PAGE_SIZE) {
    const { data, error } = await db
      .from('observations')
      .select('*')
      .order('captured_at', { ascending: false })
      .range(from, from + PAGE_SIZE - 1);
    if (error) throw error;
    all.push(...data);
    if (data.length < PAGE_SIZE) return all;
  }
}

function visibleRows() {
  const subject = $('filter-subject').value;
  const growth = $('filter-growth').value;
  const status = $('filter-status').value;
  return rows.filter(
    (row) =>
      (subject === 'all' || row.subject === 'ivy') &&
      (!growth || row.growth_form === growth) &&
      (!status || row.status === status),
  );
}

function color(row) {
  if (row.subject !== 'ivy') return '#6b7280';
  if (row.growth_form === 'ground') return '#2563eb';
  if (row.trunk_height === 'canopy') return '#b91c1c';
  if (row.trunk_height === 'mid_trunk') return '#ea580c';
  return '#ca8a04';
}

function render(fitToData) {
  const visible = visibleRows();
  const located = visible.filter((row) => row.lat != null);
  markers.clearLayers();
  for (const row of located) {
    L.circleMarker([row.lat, row.lon], {
      radius: 9,
      color: '#ffffff',
      weight: 2,
      fillColor: color(row),
      fillOpacity: 0.95,
    })
      .bindPopup(() => popup(row), { minWidth: 240 })
      .addTo(markers);
  }
  if (fitToData && located.length) {
    map.fitBounds(L.latLngBounds(located.map((row) => [row.lat, row.lon])).pad(0.2), { maxZoom: 17 });
  }
  const unlocated = visible.length - located.length;
  $('summary').textContent =
    `${located.length} on map` + (unlocated ? `, ${unlocated} without a location` : '');
}

// Built from DOM nodes rather than HTML strings so notes can't inject markup.
function popup(row) {
  const root = el('div', { className: 'popup' });

  const img = el('img', { alt: 'Observation photo' });
  root.append(img);
  db.storage
    .from(BUCKET)
    .createSignedUrl(row.photo_path, 3600)
    .then(({ data, error }) => {
      if (error) img.alt = `Photo unavailable: ${error.message}`;
      else img.src = data.signedUrl;
    });

  const facts = el('dl');
  const fact = (name, value) => {
    if (value == null || value === '') return;
    facts.append(el('dt', { textContent: name }), el('dd', { textContent: value }));
  };
  fact('Shows', LABELS[row.subject]);
  fact('Growth', LABELS[row.growth_form]);
  fact('Height', LABELS[row.trunk_height]);
  if (row.mature) fact('Mature', 'Flowers or berries');
  if (row.vines_cut) fact('Treatment', 'Vines cut');
  fact('Taken', new Date(row.captured_at).toLocaleString());
  fact('GPS', row.accuracy_m == null ? null : `±${Math.round(row.accuracy_m)} m`);
  if (row.model_version) {
    fact('Model', `ivy score ${Number(row.model_score).toFixed(2)} (${row.model_version})`);
  }
  fact('Notes', row.notes);
  root.append(facts);

  const status = el('select', { ariaLabel: 'Status' });
  for (const value of STATUSES) {
    status.append(el('option', { value, textContent: value[0].toUpperCase() + value.slice(1) }));
  }
  status.value = row.status;
  status.addEventListener('change', async () => {
    const previous = row.status;
    const { error } = await db.from('observations').update({ status: status.value }).eq('id', row.id);
    if (error) {
      status.value = previous;
      alert(`Could not update status: ${error.message}`);
      return;
    }
    row.status = status.value;
  });
  root.append(status);

  if (row.observer === user.id) {
    const remove = el('button', { type: 'button', textContent: 'Delete this observation' });
    remove.addEventListener('click', () => deleteRow(row));
    root.append(remove);
  }
  return root;
}

async function deleteRow(row) {
  if (!confirm('Delete this observation and its photo? This cannot be undone.')) return;
  const { error } = await db.from('observations').delete().eq('id', row.id);
  if (error) {
    alert(`Could not delete: ${error.message}`);
    return;
  }
  await db.storage.from(BUCKET).remove([row.photo_path]);
  rows = rows.filter((other) => other.id !== row.id);
  map.closePopup();
  render(false);
}

function el(tag, props = {}) {
  return Object.assign(document.createElement(tag), props);
}

// ---------- Export ----------

const EXPORT_COLUMNS = [
  'id', 'captured_at', 'subject', 'growth_form', 'trunk_height', 'mature', 'vines_cut',
  'status', 'lat', 'lon', 'accuracy_m', 'notes', 'photo_path', 'observer',
  'model_version', 'model_class', 'model_score', 'user_confirmed',
];

function exportCsv() {
  const cell = (value) => {
    if (value == null) return '';
    const text = String(value);
    return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  const lines = [EXPORT_COLUMNS.join(',')];
  for (const row of visibleRows()) lines.push(EXPORT_COLUMNS.map((column) => cell(row[column])).join(','));
  download('ivy-observations.csv', 'text/csv', lines.join('\r\n'));
}

function exportGeoJson() {
  const features = visibleRows()
    .filter((row) => row.lat != null)
    .map((row) => {
      const { lat, lon, ...properties } = row;
      return { type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties };
    });
  download('ivy-observations.geojson', 'application/geo+json', JSON.stringify({ type: 'FeatureCollection', features }));
}

function download(name, type, text) {
  const link = el('a', { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  link.click();
  URL.revokeObjectURL(link.href);
}
