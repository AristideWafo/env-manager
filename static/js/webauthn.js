/* Minimal WebAuthn glue: base64url <-> ArrayBuffer, and the two ceremonies.
 * No external lib — talks straight to navigator.credentials and /api/v1/auth/webauthn/*.
 */

function b64urlToBuffer(b64url) {
  const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
  const b64 = (b64url + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const buf = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
  return buf.buffer;
}

function bufferToB64url(buf) {
  const bytes = new Uint8Array(buf);
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]').content;
}

async function apiPost(path, body) {
  const res = await fetch(`/api/v1${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.error ? json.error.message : "request failed");
  return json.data;
}

function optionsJsonToCreateOptions(json) {
  const opts = JSON.parse(json);
  opts.challenge = b64urlToBuffer(opts.challenge);
  opts.user.id = b64urlToBuffer(opts.user.id);
  if (opts.excludeCredentials) {
    opts.excludeCredentials = opts.excludeCredentials.map((c) => ({ ...c, id: b64urlToBuffer(c.id) }));
  }
  return opts;
}

function optionsJsonToGetOptions(json) {
  const opts = JSON.parse(json);
  opts.challenge = b64urlToBuffer(opts.challenge);
  if (opts.allowCredentials) {
    opts.allowCredentials = opts.allowCredentials.map((c) => ({ ...c, id: b64urlToBuffer(c.id) }));
  }
  return opts;
}

function credentialToJson(cred, kind) {
  const base = {
    id: cred.id,
    rawId: bufferToB64url(cred.rawId),
    type: cred.type,
    clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
  };
  if (kind === "create") {
    base.response = {
      clientDataJSON: bufferToB64url(cred.response.clientDataJSON),
      attestationObject: bufferToB64url(cred.response.attestationObject),
    };
  } else {
    base.response = {
      clientDataJSON: bufferToB64url(cred.response.clientDataJSON),
      authenticatorData: bufferToB64url(cred.response.authenticatorData),
      signature: bufferToB64url(cred.response.signature),
      userHandle: cred.response.userHandle ? bufferToB64url(cred.response.userHandle) : null,
    };
  }
  return base;
}

async function registerPasskey(invitationToken, deviceLabel) {
  const { json, challenge } = await apiPost("/auth/webauthn/register/options", { invitation_token: invitationToken });
  const publicKey = optionsJsonToCreateOptions(json);
  const cred = await navigator.credentials.create({ publicKey });
  await apiPost("/auth/webauthn/register/verify", {
    invitation_token: invitationToken,
    challenge,
    device_label: deviceLabel || navigator.platform || "device",
    credential: credentialToJson(cred, "create"),
  });
}

async function loginWithPasskey(email) {
  const { json, challenge } = await apiPost("/auth/webauthn/login/options", { email });
  const publicKey = optionsJsonToGetOptions(json);
  const cred = await navigator.credentials.get({ publicKey });
  return apiPost("/auth/webauthn/login/verify", {
    email, challenge, credential: credentialToJson(cred, "get"),
  });
}
