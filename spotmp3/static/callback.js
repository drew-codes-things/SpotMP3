'use strict';

function showCallbackError(message) {
  document.getElementById('message').hidden = true;
  const box = document.getElementById('error');
  box.textContent = message;
  box.hidden = false;
  document.getElementById('back').hidden = false;
}

async function finishConnect() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('error')) {
    showCallbackError(`Spotify said: ${params.get('error')}. Nothing was connected.`);
    return;
  }
  const response = await fetch('/api/config', { credentials: 'same-origin' });
  if (!response.ok) {
    showCallbackError('Sign in to SpotMP3 first, then connect Spotify again.');
    return;
  }
  const config = await response.json();
  await SpotifyConnect.finish(config, params.get('code'), params.get('state'));
  window.location.replace('/');
}

finishConnect().catch(error => showCallbackError(error.message));
