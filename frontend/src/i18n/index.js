/* Oasis interface translations. No library: a flat key -> text dictionary per language, `{name}` interpolation, plural-safe
   phrasing (`tp`), a registry and a React hook.

   Adding a language = one dictionary file (copy en.js, translate the values, keep every key and every {placeholder})
   + one line in REGISTRY below + its code in oasis/agent/i18n.py (UI_LANGS), which is the server-side whitelist.
   English is the default and the competition's official language. */
import { useSyncExternalStore } from "react";
import en from "./en.js";
import zh from "./zh.js";

export const REGISTRY = {
  en: { name: "English", short: "EN", locale: "en-US", html: "en", dict: en },
  zh: { name: "简体中文", short: "中文", locale: "zh-CN", html: "zh-CN", dict: zh },
};
export const DEFAULT_LANG = "en";
export const LANG_CODES = Object.keys(REGISTRY);
const STORE_KEY = "oasis.lang";

let current = DEFAULT_LANG;
const subs = new Set();

const supported = (c) => (typeof c === "string" && Object.prototype.hasOwnProperty.call(REGISTRY, c) ? c : null);
/** "zh-CN", "zh_Hans", "EN-us" -> a registered code, or null. */
export const normalizeLang = (c) => supported(String(c || "").toLowerCase().replace("_", "-").split("-")[0]);

function stored() {
  try { return normalizeLang(localStorage.getItem(STORE_KEY)); } catch { return null; }   // storage may be blocked
}
function fromUrl() {
  try { return normalizeLang(new URLSearchParams(window.location.search).get("lang")); } catch { return null; }
}
function apply() {
  try { document.documentElement.lang = REGISTRY[current].html; } catch { /* no document (tests) */ }
}

/** Pick the starting language: ?lang= in the URL, then the saved choice, else English. Call once, before the first render. */
export function initLang() {
  current = fromUrl() || stored() || DEFAULT_LANG;
  apply();
  return current;
}

/** True when the visitor has already chosen a language (saved earlier, or ?lang= in the URL). */
export const hasChoice = () => !!(fromUrl() || stored());

export const getLang = () => current;
export const locale = () => REGISTRY[current].locale;

export function setLang(code, { persist = true } = {}) {
  const c = normalizeLang(code);
  if (!c) return current;
  if (c !== current) {
    current = c;
    apply();
    subs.forEach((f) => f());
  }
  if (persist) { try { localStorage.setItem(STORE_KEY, c); } catch { /* storage blocked: the choice lasts for this page only */ } }
  return current;
}

const subscribe = (f) => { subs.add(f); return () => subs.delete(f); };

export function interpolate(text, vars) {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined || vars[k] === null ? m : String(vars[k])));
}

/** Translate a key. Falls back to English, then to the key itself, so a missing string is visible but never breaks a page. */
export function t(key, vars) {
  const s = REGISTRY[current].dict[key] ?? REGISTRY.en.dict[key] ?? key;
  return interpolate(s, vars);
}
export const has = (key) => Object.prototype.hasOwnProperty.call(REGISTRY[current].dict, key);

/** Plural-safe phrasing: looks up `key.one` / `key.other` (CLDR category of the active locale), falling back to `.other`.
    Chinese has a single category, so its dictionary repeats the same text for both. `{n}` is filled in automatically. */
export function tp(key, n, vars) {
  let cat = "other";
  try { cat = new Intl.PluralRules(locale()).select(Number(n)); } catch { /* old engine: use .other */ }
  const k = has(`${key}.${cat}`) ? `${key}.${cat}` : `${key}.other`;
  return t(k, { n, ...vars });
}

const humanize = (s) => String(s ?? "").replace(/_/g, " ");
/** Label for a machine value, e.g. tl("status", "held"). Unknown values fall back to the value with underscores removed. */
export function tl(prefix, value) {
  const k = `${prefix}.${value}`;
  return has(k) || REGISTRY.en.dict[k] ? t(k) : humanize(value);
}

/** Server-sent English sentences that are fixed text (not engine reasons, which the API translates itself): the dictionary
    holds the exact English under a `srv.*` key. In English the text is returned unchanged. */
let serverIndex = null;
export function tm(text) {
  if (typeof text !== "string" || current === "en") return text;
  if (!serverIndex) {
    serverIndex = new Map();
    for (const [k, v] of Object.entries(REGISTRY.en.dict)) if (k.startsWith("srv.")) serverIndex.set(v, k);
  }
  const k = serverIndex.get(text);
  return k ? t(k) : text;
}

/** React hook: re-renders the component when the language changes; returns the helpers bound to the current language. */
export function useLang() {
  const lang = useSyncExternalStore(subscribe, getLang, getLang);
  return { lang, locale: REGISTRY[lang].locale, setLang, t, tp, tl, tm, languages: REGISTRY };
}
