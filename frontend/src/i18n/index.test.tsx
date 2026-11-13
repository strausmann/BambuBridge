import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LanguageSwitch } from "../shell/LanguageSwitch";
import { renderWithProviders } from "../test-utils";
import { i18n, initI18n, LANG_KEY, pickLanguage, readStoredLanguage, storeLanguage } from "./index";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("language", () => {
  it("prefers the stored choice, then the browser's first German or English language, then English", () => {
    expect(pickLanguage(["fr-FR", "de-AT", "en"])).toBe("de");
    expect(pickLanguage(["en-GB", "de"])).toBe("en");
    expect(pickLanguage(["fr", "es"])).toBe("en");
    expect(pickLanguage([])).toBe("en");
    storeLanguage("en");
    expect(pickLanguage(["de-DE"])).toBe("en");
  });

  it("ignores an unknown stored value and survives blocked site data", () => {
    localStorage.setItem(LANG_KEY, "fr");
    expect(readStoredLanguage()).toBeNull();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readStoredLanguage()).toBeNull();
    expect(() => storeLanguage("de")).not.toThrow();
  });

  it("loads both catalogs: German is the source, English is fully translated", async () => {
    await initI18n("de");
    expect(document.documentElement.lang).toBe("de");
    const german = i18n.messages;
    await initI18n("en");
    expect(document.documentElement.lang).toBe("en");
    const english = i18n.messages;
    expect(Object.keys(english).sort()).toEqual(Object.keys(german).sort());
    expect(Object.keys(english).length).toBeGreaterThan(40);
    for (const [id, message] of Object.entries(english)) expect(message, id).not.toEqual("");
  });
});

describe("LanguageSwitch", () => {
  it("names the other language in that language and switches to it", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LanguageSwitch />);
    const toEnglish = screen.getByRole("button", { name: "Switch to English" });
    expect(toEnglish).toHaveAttribute("lang", "en");

    await user.click(toEnglish);
    await waitFor(() => expect(i18n.locale).toBe("en"));
    expect(localStorage.getItem(LANG_KEY)).toBe("en");
    expect(await screen.findByRole("button", { name: "Auf Deutsch wechseln" })).toHaveTextContent("DE");
  });
});
