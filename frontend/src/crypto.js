// Approver device keys. The Ed25519 PRIVATE key is generated here, in the browser, and never sent to the server;
// the server only gets the public key (POST /api/device/register) and later checks signatures against it.
//
// Why a JS library (@noble/curves, MIT, audited, ~10 KB) instead of WebCrypto Ed25519: WebCrypto Ed25519 is missing from
// older Chrome/Edge/Safari builds, and a signing path that works on some judge laptops and not others is worse than a small
// dependency. noble also runs outside secure contexts for hashing (no crypto.subtle needed to SIGN).
//
// At rest the seed is stored in localStorage WRAPPED with the user's passcode (PBKDF2-SHA256 -> AES-GCM, via WebCrypto
// when available). That protects a copied browser profile from a casual read; it does not protect against XSS or a
// compromised browser while unlocked. Honest limit, also in docs/security-self-assessment.md.
import { ed25519 } from "@noble/curves/ed25519.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { t } from "./i18n/index.js";

const te = new TextEncoder();
const hex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
export const b64 = (b) => btoa(String.fromCharCode(...b));
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
export const sha256hex = (s) => hex(sha256(te.encode(s)));
const KEY = (role) => `oasis.device.v1.${role}`;
const subtle = typeof crypto !== "undefined" ? crypto.subtle : undefined;

async function wrapKey(pass, salt) {
  const base = await subtle.importKey("raw", te.encode(pass), "PBKDF2", false, ["deriveKey"]);
  return subtle.deriveKey({ name: "PBKDF2", salt, iterations: 200000, hash: "SHA-256" }, base,
    { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

function save(role, obj) { try { localStorage.setItem(KEY(role), JSON.stringify(obj)); } catch { /* private window: key lives for this tab only */ } }
function load(role) { try { return JSON.parse(localStorage.getItem(KEY(role)) || "null"); } catch { return null; } }

const mem = {};   // role -> { seed, publicKey, keyId }; lives only in this tab's memory

function describe(role, seed) {
  const pub = ed25519.getPublicKey(seed);
  mem[role] = { role, seed, publicKey: b64(pub), keyId: hex(sha256(pub)).slice(0, 16) };
  return mem[role];
}

export const deviceOf = (role) => mem[role] || null;
export const hasStoredDevice = (role) => !!load(role);

/** Unlock the stored device key with the passcode, or create a new one. Returns { role, publicKey, keyId, created }. */
export async function unlockDevice(role, passcode) {
  const st = load(role);
  if (st?.wrapped && subtle) {
    try {
      const key = await wrapKey(passcode, unb64(st.wrapped.salt));
      const seed = new Uint8Array(await subtle.decrypt({ name: "AES-GCM", iv: unb64(st.wrapped.iv) }, key, unb64(st.wrapped.ct)));
      return { ...describe(role, seed), created: false };
    } catch { /* wrong passcode (e.g. the server's passcode changed): fall through and make a fresh key */ }
  } else if (st?.seed) {
    return { ...describe(role, unb64(st.seed)), created: false };
  }
  const seed = crypto.getRandomValues(new Uint8Array(32));
  if (subtle) {
    const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
    const ct = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv }, await wrapKey(passcode, salt), seed));
    save(role, { v: 1, wrapped: { salt: b64(salt), iv: b64(iv), ct: b64(ct) } });
  } else {
    save(role, { v: 1, seed: b64(seed) });     // insecure context without WebCrypto: stored unwrapped
  }
  return { ...describe(role, seed), created: true };
}

export function lockDevice(role) { delete mem[role]; }

/**
 * Sign an approval for a pending payment. Refuses unless the displayed draft is exactly what the server's hash covers:
 * sha256(canonical) must equal draft_hash AND the canonical string must parse to the very fields shown to the human.
 * Message: "oasis-approval-v1|<role>|<draft_hash>" (matches oasis/trust/approvals.py).
 */
export function signApproval(role, draft) {
  const dev = mem[role];
  if (!dev) throw new Error(t("crypto.locked"));
  if (!draft?.canonical || !draft?.draft_hash) throw new Error(t("crypto.nodraft"));
  if (sha256hex(draft.canonical) !== draft.draft_hash) throw new Error(t("crypto.hashmismatch"));
  const c = JSON.parse(draft.canonical);
  for (const k of ["payee_id", "account_ref", "amount", "currency", "purpose", "route_id", "not_after", "nonce"]) {
    if (c[k] !== draft[k]) throw new Error(t("crypto.fielddiffers", { field: k }));
  }
  const sig = ed25519.sign(te.encode(`oasis-approval-v1|${role}|${draft.draft_hash}`), dev.seed);
  return { signature: b64(sig), key_id: dev.keyId };
}

/** Sign a plan-conversion consent (the draft carries its own canonical string + hash). */
export function signConsent(role, d) {
  const dev = mem[role];
  if (!dev) throw new Error(t("crypto.locked"));
  if (sha256hex(d.canonical) !== d.draft_hash) throw new Error(t("crypto.consenthash"));
  return { signature: b64(ed25519.sign(te.encode(`oasis-approval-v1|${role}|${d.draft_hash}`), dev.seed)), key_id: dev.keyId };
}
