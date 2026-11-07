'use strict';

const CLIENT_HEADERS = { 'Content-Type': 'application/json', 'X-SpotMP3': '1' };
const form = document.querySelector('form');
const errorBox = document.getElementById('error');
const submit = document.getElementById('submit');
const isSetup = form.id === 'setup';

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function readForm() {
  const values = { email: form.email.value.trim(), password: form.password.value };
  if (isSetup) values.confirm = form.confirm.value;
  return values;
}

function problemWith(values) {
  if (!values.email || !values.password) return 'Enter your email and password.';
  if (isSetup && values.password !== values.confirm) return 'The two passwords do not match.';
  return null;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  errorBox.hidden = true;
  const values = readForm();
  const problem = problemWith(values);
  if (problem) {
    showError(problem);
    return;
  }
  submit.disabled = true;
  try {
    const response = await fetch(isSetup ? '/api/setup' : '/api/signin', {
      method: 'POST',
      credentials: 'same-origin',
      headers: CLIENT_HEADERS,
      body: JSON.stringify(values),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      showError(body.error || `that did not work (${response.status})`);
      return;
    }
    window.location.replace('/');
  } catch {
    showError("Couldn't reach the server. Check your connection and try again.");
  } finally {
    submit.disabled = false;
  }
});
