// Passkeys (WebAuthn): the browser/OS holds the private key; the server stores only the public key and checks a signed challenge.
import { api } from "./api.js";

const b64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64u = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(s.length / 4) * 4, "=")), (c) => c.charCodeAt(0)).buffer;

export const passkeysSupported = () => typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator.credentials;

const creationOptions = (o) => ({ ...o, challenge: unb64u(o.challenge), user: { ...o.user, id: unb64u(o.user.id) },
  excludeCredentials: (o.excludeCredentials || []).map((c) => ({ ...c, id: unb64u(c.id) })) });
const requestOptions = (o) => ({ ...o, challenge: unb64u(o.challenge), allowCredentials: (o.allowCredentials || []).map((c) => ({ ...c, id: unb64u(c.id) })) });

/** Register a passkey for the logged-in role. */
export async function registerPasskey() {
  const b = await api("/auth/passkey/register/begin", {});
  const c = await navigator.credentials.create({ publicKey: creationOptions(b.options) });
  const credential = { id: c.id, rawId: b64u(c.rawId), type: c.type,
    response: { clientDataJSON: b64u(c.response.clientDataJSON), attestationObject: b64u(c.response.attestationObject),
      transports: c.response.getTransports ? c.response.getTransports() : undefined } };
  return api("/auth/passkey/register/finish", { challenge_id: b.challenge_id, credential });
}

/** Second login factor: answer the challenge the passcode step returned. */
export async function assertPasskey(step) {
  const a = await navigator.credentials.get({ publicKey: requestOptions(step.options) });
  const credential = { id: a.id, rawId: b64u(a.rawId), type: a.type,
    response: { clientDataJSON: b64u(a.response.clientDataJSON), authenticatorData: b64u(a.response.authenticatorData),
      signature: b64u(a.response.signature), userHandle: a.response.userHandle ? b64u(a.response.userHandle) : undefined } };
  return api("/auth/passkey/login/finish", { challenge_id: step.challenge_id, credential });
}
