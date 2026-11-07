'use strict';

const CLIENT_HEADERS = { 'Content-Type': 'application/json', 'X-SpotMP3': '1' };
const BUSY_POLL_MS = 2500;
const IDLE_POLL_MS = 15000;
const CONFIRM_WINDOW_MS = 3000;
const SPOTIFY_PLAYLIST_LINK = /^(?:https?:\/\/open\.spotify\.com\/(?:intl-[a-z-]+\/)?(?:embed\/)?playlist\/|spotify:playlist:)([A-Za-z0-9]{22})/i;
const OPEN_STATUSES = ['queued', 'working'];
const FINISHED_STATUSES = ['done', 'failed', 'cancelled', 'expired'];
const STATUS_LABELS = { queued: 'Waiting', working: 'Converting', done: 'Ready', failed: 'Failed', cancelled: 'Cancelled', expired: 'Cleaned up' };

const state = { config: null, result: null, selected: new Set(), expanded: new Set(), details: new Map(), pollTimer: null };

const byId = id => document.getElementById(id);

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children) if (child) node.append(child);
  return node;
}

function showMessage(box, message) {
  box.textContent = message || '';
  box.hidden = !message;
}

async function api(path, options = {}) {
  const writes = options.method && options.method !== 'GET';
  const response = await fetch(path, { credentials: 'same-origin', ...options, headers: writes ? CLIENT_HEADERS : {} });
  if (response.status === 401) {
    window.location.replace('/');
    throw new Error('Signed out.');
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error((body && body.error) || `Request failed (${response.status}).`);
  return body;
}

function post(path, data) {
  return api(path, { method: 'POST', body: JSON.stringify(data || {}) });
}

function formatTime(milliseconds) {
  const seconds = Math.round(milliseconds / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

function formatSize(bytes) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function coverImage(url) {
  return url ? el('img', { class: 'cover', src: url, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' }) : el('span', { class: 'cover' });
}

function withBusy(button, task) {
  return async (...args) => {
    button.disabled = true;
    try {
      await task(...args);
    } finally {
      button.disabled = false;
    }
  };
}

function confirmFirst(button, label, action) {
  let armedUntil = 0;
  button.addEventListener('click', () => {
    if (Date.now() < armedUntil) {
      armedUntil = 0;
      action();
      return;
    }
    armedUntil = Date.now() + CONFIRM_WINDOW_MS;
    button.textContent = 'Sure?';
    setTimeout(() => { button.textContent = label; }, CONFIRM_WINDOW_MS);
  });
  return button;
}

function showResult(collection) {
  state.result = collection;
  state.selected = new Set(collection.tracks.map((_, index) => index));
  byId('result-name').textContent = collection.name;
  const notes = [];
  if (collection.truncated && collection.kind === 'playlist' && !SpotifyConnect.isConnected()) {
    notes.push('Spotify only shares the first 100 tracks of a playlist link. Connect Spotify below the link box to get every track.');
  } else if (collection.truncated) {
    notes.push(`Only the first ${collection.tracks.length} tracks are listed (the most one job can hold).`);
  }
  showMessage(byId('result-note'), notes.join(' '));
  showMessage(byId('convert-error'), '');
  renderTracks();
  byId('result').hidden = false;
  byId('result').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderTracks() {
  const list = byId('tracks');
  list.replaceChildren(...state.result.tracks.map((track, index) => {
    const box = el('input', { type: 'checkbox', 'aria-label': `Include ${track.title}` });
    box.checked = state.selected.has(index);
    box.addEventListener('change', () => {
      if (box.checked) state.selected.add(index);
      else state.selected.delete(index);
      updateCount();
    });
    return el('li', { class: 'track' }, [
      box,
      coverImage(track.coverUrl),
      el('span', { class: 'name' }, [
        el('span', { class: 'title', text: track.title }),
        el('span', { class: 'artist', text: track.artists.join(', ') }),
      ]),
      el('span', { class: 'time', text: formatTime(track.durationMs) }),
    ]);
  }));
  updateCount();
}

function updateCount() {
  const total = state.result.tracks.length;
  const chosen = state.selected.size;
  byId('result-count').textContent = `${chosen} of ${total} selected`;
  byId('convert').textContent = chosen === 1 ? 'Convert 1 track' : `Convert ${chosen} tracks`;
  byId('convert').disabled = chosen === 0;
}

function setAllSelected(selected) {
  state.selected = selected ? new Set(state.result.tracks.map((_, index) => index)) : new Set();
  renderTracks();
}

async function findTracks(event) {
  event.preventDefault();
  const link = byId('link').value.trim();
  showMessage(byId('find-error'), '');
  if (!link) {
    showMessage(byId('find-error'), 'Paste a Spotify or YouTube link first.');
    return;
  }
  const spotifyPlaylist = link.match(SPOTIFY_PLAYLIST_LINK);
  try {
    const collection = spotifyPlaylist && SpotifyConnect.isConnected()
      ? await SpotifyConnect.playlist(state.config, spotifyPlaylist[1], state.config.maxTracks)
      : await post('/api/resolve', { link });
    if (!collection.tracks.length) throw new Error('No playable tracks were found at that link.');
    showResult(collection);
  } catch (error) {
    showMessage(byId('find-error'), error.message);
  }
}

async function convertSelected() {
  const tracks = state.result.tracks.filter((_, index) => state.selected.has(index));
  showMessage(byId('convert-error'), '');
  try {
    const job = await post('/api/jobs', { name: state.result.name, quality: byId('quality').value, tracks });
    state.expanded.add(job.id);
    byId('result').hidden = true;
    byId('link').value = '';
    await refreshJobs();
  } catch (error) {
    showMessage(byId('convert-error'), error.message);
  }
}

function jobProgress(job) {
  const finished = FINISHED_STATUSES.reduce((sum, status) => sum + (job.counts[status] || 0), 0);
  return job.total ? finished / job.total : 0;
}

function isJobOpen(job) {
  return OPEN_STATUSES.some(status => job.counts[status]);
}

function jobSummary(job) {
  const parts = [`${job.counts.done || 0} of ${job.total} ready`];
  if (job.counts.working) parts.push('converting');
  if (job.counts.queued) parts.push(`${job.counts.queued} waiting`);
  if (job.counts.failed) parts.push(`${job.counts.failed} failed`);
  if (job.counts.expired) parts.push(`${job.counts.expired} cleaned up`);
  return `${parts.join(', ')} · ${job.qualityLabel}`;
}

function itemRow(item) {
  const detail = item.status === 'failed'
    ? item.error
    : item.youtubeTitle ? `From YouTube: ${item.youtubeTitle}${item.fileBytes ? ` · ${formatSize(item.fileBytes)}` : ''}` : formatTime(item.durationMs);
  const actions = [];
  if (item.status === 'done') {
    actions.push(el('a', { class: 'button small', href: `/api/items/${item.id}/file`, download: item.fileName || true, text: 'Download' }));
  }
  if (item.youtubeId) {
    actions.push(el('a', { class: 'button quiet small', href: `https://www.youtube.com/watch?v=${encodeURIComponent(item.youtubeId)}`, target: '_blank', rel: 'noopener noreferrer', text: 'Source' }));
  }
  if (item.status === 'failed' || item.status === 'cancelled') {
    const retry = el('button', { class: 'quiet small', type: 'button', text: 'Retry' });
    retry.addEventListener('click', withBusy(retry, async () => {
      try {
        await post(`/api/items/${item.id}/retry`);
      } catch (error) {
        showMessage(byId('find-error'), error.message);
      }
      await refreshJobs();
    }));
    actions.push(retry);
  }
  return el('li', { class: 'job-item' }, [
    el('div', {}, [
      el('div', {}, [el('span', { text: `${item.artists.join(', ')} - ${item.title} ` }), el('span', { class: `status ${item.status}`, text: STATUS_LABELS[item.status] || item.status })]),
      el('div', { class: 'detail', text: detail || '' }),
    ]),
    el('div', { class: 'actions' }, actions),
  ]);
}

function jobCard(job) {
  const open = isJobOpen(job);
  const expanded = state.expanded.has(job.id);
  const toggle = el('button', { class: 'quiet small', type: 'button', text: expanded ? 'Hide tracks' : 'Show tracks' });
  toggle.addEventListener('click', () => {
    if (expanded) state.expanded.delete(job.id);
    else state.expanded.add(job.id);
    refreshJobs();
  });
  const buttons = [toggle];
  if (job.counts.done) buttons.push(el('a', { class: 'button small', href: `/api/jobs/${job.id}/zip`, download: true, text: 'Download all (.zip)' }));
  if (open) {
    const cancel = el('button', { class: 'quiet small', type: 'button', text: 'Stop' });
    buttons.push(confirmFirst(cancel, 'Stop', () => post(`/api/jobs/${job.id}/cancel`).then(refreshJobs, error => showMessage(byId('find-error'), error.message))));
  }
  const remove = el('button', { class: 'quiet small', type: 'button', text: 'Delete' });
  buttons.push(confirmFirst(remove, 'Delete', () => api(`/api/jobs/${job.id}`, { method: 'DELETE' }).then(refreshJobs, error => showMessage(byId('find-error'), error.message))));
  const bar = el('span');
  bar.style.width = `${Math.round(jobProgress(job) * 100)}%`;
  const detail = state.details.get(job.id);
  return el('article', { class: 'job' }, [
    el('div', { class: 'job-head' }, [el('strong', { text: job.name }), ...buttons]),
    el('div', { class: 'bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(jobProgress(job) * 100)) }, [bar]),
    el('div', { class: 'hint', text: jobSummary(job) }),
    expanded && detail ? el('ul', { class: 'job-items' }, detail.items.map(itemRow)) : null,
  ]);
}

async function refreshJobs() {
  window.clearTimeout(state.pollTimer);
  let busy = false;
  try {
    const { jobs } = await api('/api/jobs');
    busy = jobs.some(isJobOpen);
    const shown = jobs.filter(job => state.expanded.has(job.id));
    const details = await Promise.all(shown.map(job => api(`/api/jobs/${job.id}`)));
    state.details = new Map(details.map(detail => [detail.id, detail]));
    const container = byId('jobs');
    container.replaceChildren(...(jobs.length ? jobs.map(jobCard) : [el('p', { class: 'empty', text: 'Nothing yet. Paste a link above to start.' })]));
  } catch (error) {
    showMessage(byId('find-error'), `Could not load your conversions: ${error.message}`);
  } finally {
    state.pollTimer = window.setTimeout(refreshJobs, busy ? BUSY_POLL_MS : IDLE_POLL_MS);
  }
}

function playlistTile(name, image, onPick) {
  const button = el('button', { class: 'playlist', type: 'button' }, [coverImage(image), el('span', { text: name })]);
  button.addEventListener('click', withBusy(button, onPick));
  return button;
}

async function pickCollection(load) {
  showMessage(byId('find-error'), '');
  try {
    const collection = await load();
    if (!collection.tracks.length) throw new Error('That list has no tracks that can be converted.');
    showResult(collection);
  } catch (error) {
    showMessage(byId('find-error'), error.message);
  }
}

async function showPlaylists() {
  const box = byId('playlists');
  showMessage(byId('find-error'), '');
  try {
    const playlists = await SpotifyConnect.myPlaylists(state.config);
    const limit = state.config.maxTracks;
    box.replaceChildren(
      playlistTile('Liked Songs', null, () => pickCollection(() => SpotifyConnect.likedSongs(state.config, limit))),
      ...playlists.map(playlist => playlistTile(playlist.name, playlist.image, () => pickCollection(() => SpotifyConnect.playlist(state.config, playlist.id, limit)))),
    );
    box.hidden = false;
  } catch (error) {
    showMessage(byId('find-error'), error.message);
    setupSpotify();
  }
}

function setupSpotify() {
  const configured = SpotifyConnect.isConfigured(state.config);
  byId('spotify-row').hidden = !configured;
  if (!configured) return;
  const connected = SpotifyConnect.isConnected();
  byId('spotify-connect').hidden = connected;
  byId('spotify-playlists').hidden = !connected;
  byId('spotify-disconnect').hidden = !connected;
  byId('spotify-status').textContent = connected
    ? 'Spotify is connected in this tab. Pasted playlist links now include every track.'
    : 'Connect to pick from your own playlists and Liked Songs, and to get playlists longer than 100 tracks.';
  if (!connected) byId('playlists').hidden = true;
}

async function loadAccounts() {
  const { accounts } = await api('/api/accounts');
  byId('accounts').replaceChildren(...accounts.map(account => {
    const remove = el('button', { class: 'quiet small', type: 'button', text: 'Remove' });
    confirmFirst(remove, 'Remove', () => api(`/api/accounts/${account.id}`, { method: 'DELETE' })
      .then(loadAccounts, error => showMessage(byId('account-error'), error.message)));
    const isMe = account.email === state.config.user.email;
    return el('li', {}, [el('span', { text: `${account.email}${account.isAdmin ? ' (admin)' : ''}${isMe ? ' (you)' : ''}` }), isMe ? null : remove]);
  }));
}

async function addAccount(event) {
  event.preventDefault();
  showMessage(byId('account-error'), '');
  try {
    await post('/api/accounts', {
      email: byId('new-email').value.trim(),
      password: byId('new-password').value,
      confirm: byId('new-confirm').value,
      isAdmin: byId('new-admin').checked,
    });
    event.target.reset();
    await loadAccounts();
  } catch (error) {
    showMessage(byId('account-error'), error.message);
  }
}

function setupAccounts() {
  if (!state.config.canManageAccounts) return;
  const toggle = byId('accounts-toggle');
  toggle.hidden = false;
  toggle.addEventListener('click', async () => {
    const card = byId('accounts-card');
    card.hidden = !card.hidden;
    if (!card.hidden) {
      await loadAccounts().catch(error => showMessage(byId('account-error'), error.message));
      card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
  byId('account-form').addEventListener('submit', addAccount);
}

function setupQuality() {
  const select = byId('quality');
  select.replaceChildren(...state.config.qualities.map(quality => el('option', { value: quality.key, text: quality.label })));
  select.value = state.config.defaultQuality;
}

async function start() {
  state.config = await api('/api/config');
  byId('who').textContent = state.config.user.email;
  byId('retention').textContent = `Finished files are kept for ${state.config.retentionHours} hours, then cleaned up.`;
  byId('signout').hidden = !state.config.canSignOut;
  byId('signout').addEventListener('click', async () => {
    await post('/api/signout');
    SpotifyConnect.disconnect();
    window.location.replace('/');
  });
  setupQuality();
  setupAccounts();
  setupSpotify();
  byId('find-form').addEventListener('submit', withBusy(byId('find'), findTracks));
  byId('select-all').addEventListener('click', () => setAllSelected(true));
  byId('select-none').addEventListener('click', () => setAllSelected(false));
  byId('convert').addEventListener('click', withBusy(byId('convert'), convertSelected));
  byId('spotify-connect').addEventListener('click', () => SpotifyConnect.start(state.config).catch(error => showMessage(byId('find-error'), error.message)));
  byId('spotify-playlists').addEventListener('click', withBusy(byId('spotify-playlists'), showPlaylists));
  byId('spotify-disconnect').addEventListener('click', () => {
    SpotifyConnect.disconnect();
    setupSpotify();
  });
  await refreshJobs();
}

start().catch(error => showMessage(byId('find-error'), `SpotMP3 could not start: ${error.message}`));
