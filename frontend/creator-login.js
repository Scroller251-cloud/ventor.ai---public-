(() => {
  const state = { challenge: null, expiresAt: 0 };
  const b64ToBytes = (value) => {
    const normalized = value.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(value.length / 4) * 4, '=');
    const raw = atob(normalized);
    return Uint8Array.from(raw, c => c.charCodeAt(0));
  };
  const canonical = (claims) => JSON.stringify(claims, Object.keys(claims).sort());
  async function getChallenge() {
    const response = await fetch('/api/owner/challenge', { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error('Unable to obtain an Owner challenge.');
    const data = await response.json();
    state.challenge = data.challenge;
    state.expiresAt = Date.now() + data.expires_in * 1000;
    return data;
  }
  async function signEd25519(privateKeyBase64, claims) {
    if (!window.crypto?.subtle) throw new Error('Web Crypto is unavailable in this browser.');
    const key = await crypto.subtle.importKey('pkcs8', b64ToBytes(privateKeyBase64), { name: 'Ed25519' }, false, ['sign']);
    const signature = await crypto.subtle.sign('Ed25519', key, new TextEncoder().encode(canonical(claims)));
    let binary = '';
    for (const byte of new Uint8Array(signature)) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }
  async function authenticate({ keyId, privateKeyBase64 }) {
    if (!keyId || !privateKeyBase64) throw new Error('Key ID and Ed25519 PKCS#8 private key are required.');
    if (!state.challenge || Date.now() >= state.expiresAt) await getChallenge();
    const claims = { challenge: state.challenge, issued_at: Math.floor(Date.now() / 1000), key_id: keyId };
    const signature = await signEd25519(privateKeyBase64.trim(), claims);
    const response = await fetch('/api/owner/login', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ challenge: state.challenge, claims, signature }) });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Owner authentication failed.');
    }
    const result = await response.json();
    state.challenge = null;
    state.expiresAt = 0;
    sessionStorage.setItem('ventor_owner_session', result.token);
    return result;
  }
  function getAuthorizationHeader() {
    const token = sessionStorage.getItem('ventor_owner_session');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }
  function logout() { sessionStorage.removeItem('ventor_owner_session'); }
  window.VentorOwnerAuth = { getChallenge, authenticate, getAuthorizationHeader, logout };
})();
