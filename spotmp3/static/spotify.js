'use strict';

const SpotifyConnect = (() => {
  const TOKEN_KEY = 'spotmp3.spotify.token';
  const VERIFIER_KEY = 'spotmp3.spotify.verifier';
  const STATE_KEY = 'spotmp3.spotify.state';
  const AUTHORIZE_URL = 'https://accounts.spotify.com/authorize';
  const TOKEN_URL = 'https://accounts.spotify.com/api/token';
  const API_URL = 'https://api.spotify.com/v1';
  const SCOPES = 'playlist-read-private playlist-read-collaborative user-library-read';
  const EXPIRY_MARGIN_MS = 60 * 1000;
  const MAX_TEXT = 300;
  const MAX_ARTISTS = 20;

  function read(key) {
    try {
      return sessionStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function write(key, value) {
    try {
      if (value === null) sessionStorage.removeItem(key);
      else sessionStorage.setItem(key, value);
    } catch {
      throw new Error('This browser blocks storage, so Spotify cannot stay connected.');
    }
  }

  function base64url(bytes) {
    let text = '';
    for (const byte of new Uint8Array(bytes)) text += String.fromCharCode(byte);
    return btoa(text).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
  }

  function randomText(length) {
    return base64url(crypto.getRandomValues(new Uint8Array(length)));
  }

  function isConfigured(config) {
    return Boolean(config && config.spotifyClientId && config.spotifyRedirectUri);
  }

  async function start(config) {
    const verifier = randomText(64);
    const state = randomText(16);
    const challenge = base64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)));
    write(VERIFIER_KEY, verifier);
    write(STATE_KEY, state);
    const params = new URLSearchParams({
      client_id: config.spotifyClientId,
      response_type: 'code',
      redirect_uri: config.spotifyRedirectUri,
      code_challenge_method: 'S256',
      code_challenge: challenge,
      scope: SCOPES,
      state,
    });
    window.location.assign(`${AUTHORIZE_URL}?${params}`);
  }

  function saveToken(body, previousRefresh) {
    if (!body || typeof body.access_token !== 'string') throw new Error('Spotify sent back an unexpected answer.');
    const token = {
      accessToken: body.access_token,
      refreshToken: body.refresh_token || previousRefresh || null,
      expiresAt: Date.now() + (Number(body.expires_in) || 3600) * 1000,
    };
    write(TOKEN_KEY, JSON.stringify(token));
    return token;
  }

  async function requestToken(fields) {
    const response = await fetch(TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(fields),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(`Spotify refused the connection: ${body.error_description || body.error || response.status}`);
    return body;
  }

  async function finish(config, code, state) {
    const expectedState = read(STATE_KEY);
    const verifier = read(VERIFIER_KEY);
    write(STATE_KEY, null);
    write(VERIFIER_KEY, null);
    if (!code || !state || !expectedState || state !== expectedState || !verifier) {
      throw new Error('That Spotify sign-in did not start here, so it was ignored. Try Connect Spotify again.');
    }
    const body = await requestToken({
      client_id: config.spotifyClientId,
      grant_type: 'authorization_code',
      code,
      redirect_uri: config.spotifyRedirectUri,
      code_verifier: verifier,
    });
    saveToken(body, null);
  }

  function storedToken() {
    try {
      return JSON.parse(read(TOKEN_KEY) || 'null');
    } catch {
      return null;
    }
  }

  function isConnected() {
    return storedToken() !== null;
  }

  function disconnect() {
    write(TOKEN_KEY, null);
  }

  async function accessToken(config) {
    const token = storedToken();
    if (!token) throw new Error('Connect Spotify first.');
    if (Date.now() < token.expiresAt - EXPIRY_MARGIN_MS) return token.accessToken;
    if (!token.refreshToken) {
      disconnect();
      throw new Error('Your Spotify connection ran out. Connect Spotify again.');
    }
    const body = await requestToken({ client_id: config.spotifyClientId, grant_type: 'refresh_token', refresh_token: token.refreshToken });
    return saveToken(body, token.refreshToken).accessToken;
  }

  async function get(config, pathOrUrl) {
    const url = pathOrUrl.startsWith('https://') ? pathOrUrl : `${API_URL}${pathOrUrl}`;
    if (!url.startsWith(`${API_URL}/`)) throw new Error('Spotify sent a link outside its API.');
    const response = await fetch(url, { headers: { Authorization: `Bearer ${await accessToken(config)}` } });
    const body = await response.json().catch(() => ({}));
    if (response.status === 401) {
      disconnect();
      throw new Error('Spotify signed you out. Connect Spotify again.');
    }
    if (!response.ok) throw new Error(`Spotify answered ${response.status}: ${(body.error && body.error.message) || 'no details'}`);
    return body;
  }

  async function pages(config, firstPath, limit) {
    const items = [];
    let next = firstPath;
    while (next && items.length < limit) {
      const page = await get(config, next);
      items.push(...(page.items || []));
      next = page.next;
    }
    return { items: items.slice(0, limit), truncated: Boolean(next) || items.length > limit };
  }

  function clip(text) {
    return String(text || '').slice(0, MAX_TEXT);
  }

  function biggestImage(images) {
    const sorted = (images || []).filter(image => image && image.url).sort((a, b) => (b.width || 0) - (a.width || 0));
    return sorted.length ? sorted[0].url : null;
  }

  function trackJson(track) {
    if (!track || track.type !== 'track' || !track.id || track.is_local || !track.duration_ms || !track.name) return null;
    const artists = (track.artists || []).map(artist => clip(artist && artist.name)).filter(Boolean).slice(0, MAX_ARTISTS);
    return {
      title: clip(track.name),
      artists: artists.length ? artists : ['Unknown artist'],
      durationMs: track.duration_ms,
      spotifyId: track.id,
      album: track.album ? clip(track.album.name) || null : null,
      trackNumber: track.track_number > 0 ? track.track_number : null,
      coverUrl: track.album ? biggestImage(track.album.images) : null,
    };
  }

  function entryTracks(entries) {
    return entries.map(entry => trackJson(entry && (entry.item || entry.track))).filter(Boolean);
  }

  async function myPlaylists(config) {
    const { items } = await pages(config, '/me/playlists?limit=50', 500);
    return items.filter(Boolean).map(playlist => ({ id: playlist.id, name: playlist.name || 'Untitled playlist', image: biggestImage(playlist.images) }));
  }

  async function playlist(config, playlistId, limit) {
    const details = await get(config, `/playlists/${encodeURIComponent(playlistId)}?fields=name`);
    const { items, truncated } = await pages(config, `/playlists/${encodeURIComponent(playlistId)}/items?limit=100&additional_types=track`, limit);
    return { kind: 'playlist', name: details.name || 'Playlist', truncated, tracks: entryTracks(items) };
  }

  async function likedSongs(config, limit) {
    const { items, truncated } = await pages(config, '/me/tracks?limit=50', limit);
    return { kind: 'playlist', name: 'Liked Songs', truncated, tracks: entryTracks(items) };
  }

  return { isConfigured, isConnected, start, finish, disconnect, myPlaylists, playlist, likedSongs };
})();
