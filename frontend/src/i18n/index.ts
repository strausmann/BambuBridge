import { i18n, type Messages } from "@lingui/core";

export type Lang = "de" | "en";

export const LANGUAGES: readonly Lang[] = ["de", "en"];

/** Where the user's explicit language choice is remembered. */
export const LANG_KEY = "bb.lang";

export function isLang(value: unknown): value is Lang {
  return value === "de" || value === "en";
}

export function readStoredLanguage(): Lang | null {
  try {
    const value = localStorage.getItem(LANG_KEY);
    return isLang(value) ? value : null;
  } catch {
    return null; // private window, blocked site data
  }
}

export function storeLanguage(lang: Lang): void {
  try {
    localStorage.setItem(LANG_KEY, lang);
  } catch {
    /* the choice then lasts for this page load only */
  }
}

/** Order: the user's choice, then the browser's languages (first German or English one), then English. */
export function pickLanguage(browserLanguages: readonly string[] = navigator.languages): Lang {
  const stored = readStoredLanguage();
  if (stored) return stored;
  for (const tag of browserLanguages) {
    const base = tag.toLowerCase().split("-")[0];
    if (isLang(base)) return base;
  }
  return "en";
}

function loadMessages(lang: Lang): Promise<{ messages: Messages }> {
  return lang === "de" ? import("./locales/de/messages.po") : import("./locales/en/messages.po");
}

export async function initI18n(lang: Lang): Promise<void> {
  const { messages } = await loadMessages(lang);
  i18n.load(lang, messages);
  i18n.activate(lang);
  document.documentElement.lang = lang;
}

/** Switch the language at runtime and remember the choice. */
export async function changeLanguage(lang: Lang): Promise<void> {
  storeLanguage(lang);
  await initI18n(lang);
}

export { i18n };
