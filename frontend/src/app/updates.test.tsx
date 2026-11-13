import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, resetVersionSignal, VERSION_HEADER } from "../api/client";
import { UpdateBanner } from "../shell/UpdateBanner";
import { jsonResponse, renderWithProviders, stubFetch } from "../test-utils";
import { useDirtyGuard } from "./dirtyGuard";
import { MAX_RELOADS_PER_SESSION, RELOAD_GUARD_KEY, resetUpdatesForTest, startUpdates, UPDATE_CHECK_INTERVAL_MS, type RegisterSW } from "./updates";

/** sessionStorage survives a reload; this one survives a "new page" in the test as well. */
class MemoryStorage {
  values = new Map<string, string>();
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

interface FakeRegistration {
  update: ReturnType<typeof vi.fn>;
  installing: object | null;
  waiting: object | null;
}

let storage: MemoryStorage;
let reloads: string[];
/** Every started page is stopped after its test, also when an assertion failed half-way. */
const running: (() => void)[] = [];

/** One page load: a registered worker, the update hooks, a fetch that reports `serverVersion`. */
function startPage(registration: FakeRegistration | undefined = { update: vi.fn(() => Promise.resolve()), installing: null, waiting: null }) {
  resetUpdatesForTest();
  resetVersionSignal();
  const updateSW = vi.fn((reloadPage?: boolean) => {
    if (reloadPage) reloads.push("skip-waiting");
    return Promise.resolve();
  });
  let needRefresh: (() => void) | undefined;
  const register: RegisterSW = (options) => {
    needRefresh = options.onNeedRefresh;
    options.onRegisteredSW?.("/sw.js", registration as unknown as ServiceWorkerRegistration);
    return updateSW;
  };
  const stop = startUpdates(register, { storage, reload: () => reloads.push("reload"), waitForWorkerMs: 50, waitForController: () => Promise.resolve() });
  running.push(stop);
  return { stop, updateSW, registration, needRefresh: () => needRefresh?.() };
}

async function answerWith(version: string) {
  stubFetch({ "GET /api/v1/info": () => jsonResponse({ name: "BambuBridge", version: "x", build: "y" }, { headers: { [VERSION_HEADER]: version } }) });
  await act(async () => {
    await apiFetch("/api/v1/info");
    // Let the reload decision (which awaits the worker update) settle.
    await new Promise((resolve) => setTimeout(resolve, 80));
  });
}

beforeEach(() => {
  storage = new MemoryStorage();
  reloads = [];
});

afterEach(() => {
  running.splice(0).forEach((stop) => stop());
  vi.useRealTimers();
  resetUpdatesForTest();
});

describe("version check", () => {
  it("the same version as this page changes nothing", async () => {
    const page = startPage();
    await answerWith(__APP_VERSION__);
    expect(reloads).toEqual([]);
    expect(page.registration!.update).not.toHaveBeenCalled();
    page.stop();
  });

  it("a different server version: the worker is asked for an update, then the page reloads exactly once", async () => {
    const page = startPage();
    await answerWith("9.9.9+next");
    expect(page.registration!.update).toHaveBeenCalled();
    expect(reloads).toEqual(["reload"]);
    expect(JSON.parse(storage.getItem(RELOAD_GUARD_KEY)!)).toEqual(["9.9.9+next"]);
    // The same answer again on this page: still one reload.
    await answerWith("9.9.9+next");
    expect(reloads).toEqual(["reload"]);
    page.stop();
  });

  it("after the reload the same difference again: no second reload, the banner instead", async () => {
    let page = startPage();
    await answerWith("9.9.9+next");
    page.stop();
    expect(reloads).toHaveLength(1);

    // The reloaded page still runs the old build (a cache in between): it must not reload in a loop.
    page = startPage();
    renderWithProviders(<UpdateBanner />);
    await answerWith("9.9.9+next");
    expect(reloads).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("Neue Version");
    page.stop();
  });

  it("a newer version after that one reloads again", async () => {
    storage.setItem(RELOAD_GUARD_KEY, JSON.stringify(["9.9.9+next"]));
    const page = startPage();
    await answerWith("9.9.10+later");
    expect(reloads).toEqual(["reload"]);
    expect(JSON.parse(storage.getItem(RELOAD_GUARD_KEY)!)).toEqual(["9.9.9+next", "9.9.10+later"]);
    page.stop();
  });

  it("two replicas on different builds behind one proxy: reloads stop after the cap, then the banner", async () => {
    // Each page load gets an answer from the other replica, alternating between two builds.
    const versions = ["9.9.9+a", "9.9.9+b", "9.9.9+a", "9.9.9+b", "9.9.9+a", "9.9.9+b"];
    for (const version of versions) {
      const page = startPage();
      renderWithProviders(<UpdateBanner />);
      await answerWith(version);
      page.stop();
    }
    expect(MAX_RELOADS_PER_SESSION).toBe(2);
    expect(reloads).toEqual(["reload", "reload"]);
    expect(screen.getAllByRole("status").at(-1)).toHaveTextContent("Neue Version");
  });

  it("a third new version in one session gets the banner, not a third reload", async () => {
    for (const version of ["9.9.9+one", "9.9.9+two", "9.9.9+three"]) {
      const page = startPage();
      await answerWith(version);
      page.stop();
    }
    expect(reloads).toEqual(["reload", "reload"]);
  });

  it("an old single-version entry (the earlier format) still counts as reloaded for", async () => {
    storage.setItem(RELOAD_GUARD_KEY, "9.9.9+next");
    const page = startPage();
    await answerWith("9.9.9+next");
    expect(reloads).toEqual([]);
    page.stop();
  });

  it.each([
    ["a checkbox", <input key="c" type="checkbox" aria-label="Field" />],
    ["a range slider", <input key="r" type="range" aria-label="Field" />],
    ["a select", <select key="s" aria-label="Field"><option>a</option></select>],
    ["a button", <button key="b" type="button" aria-label="Field" />],
  ])("a focused control that takes no typing (%s) does not hold the reload back", async (_name, element) => {
    const page = startPage();
    renderWithProviders(element);
    screen.getByLabelText("Field").focus();
    await answerWith("9.9.9+next");
    expect(reloads).toEqual(["reload"]);
    page.stop();
  });

  it.each(["text", "search", "email", "url", "tel", "password", "number"])("a focused %s field holds the reload back", async (type) => {
    const page = startPage();
    renderWithProviders(<input type={type} aria-label="Field" />);
    screen.getByLabelText("Field").focus();
    await answerWith("9.9.9+next");
    expect(reloads).toEqual([]);
    page.stop();
  });

  it("with a new worker installing, the reload goes through it (it takes over first, then one reload)", async () => {
    const registration: FakeRegistration = { update: vi.fn(() => Promise.resolve()), installing: {}, waiting: null };
    const page = startPage(registration);
    registration.update.mockImplementation(() => {
      // The new worker finishes installing shortly after the update check.
      setTimeout(() => page.needRefresh(), 10);
      return Promise.resolve();
    });
    await answerWith("9.9.9+next");
    expect(reloads).toEqual(["skip-waiting", "reload"]);
    page.stop();
  });

  it("without any worker (unsupported, or not registered) the page reloads plainly", async () => {
    const page = startPage(undefined);
    await answerWith("9.9.9+next");
    expect(reloads).toEqual(["reload"]);
    page.stop();
  });

  it("a focused field gets the banner instead of a reload; the banner reloads on request", async () => {
    const page = startPage();
    renderWithProviders(
      <>
        <input aria-label="Name" />
        <UpdateBanner />
      </>,
    );
    screen.getByLabelText("Name").focus();
    await answerWith("9.9.9+next");
    expect(reloads).toEqual([]);
    expect(screen.getByRole("status")).toHaveTextContent("Neue Version – jetzt neu laden");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Neu laden" }));
      await new Promise((resolve) => setTimeout(resolve, 80));
    });
    expect(reloads).toEqual(["reload"]);
    page.stop();
  });

  it("a changed form gets the banner instead of a reload", async () => {
    function Form() {
      useDirtyGuard(true);
      return <UpdateBanner />;
    }
    const page = startPage();
    renderWithProviders(<Form />);
    await answerWith("9.9.9+next");
    expect(reloads).toEqual([]);
    expect(screen.getByRole("status")).toHaveTextContent("Neue Version");
    page.stop();
  });

  it("the banner stays hidden while nothing is pending", () => {
    const page = startPage();
    renderWithProviders(<UpdateBanner />);
    expect(screen.queryByRole("status")).toBeNull();
    page.stop();
  });
});

describe("update checks", () => {
  it("when the page becomes visible again and every 30 minutes", () => {
    vi.useFakeTimers();
    const page = startPage();
    const update = page.registration!.update;
    expect(update).not.toHaveBeenCalled();

    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(update).not.toHaveBeenCalled();
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(update).toHaveBeenCalledTimes(1);

    expect(UPDATE_CHECK_INTERVAL_MS).toBe(30 * 60 * 1000);
    vi.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS);
    expect(update).toHaveBeenCalledTimes(2);

    page.stop();
    vi.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(update).toHaveBeenCalledTimes(2);
  });

  it("a failing update check is swallowed (offline, server gone)", async () => {
    const page = startPage({ update: vi.fn(() => Promise.reject(new Error("offline"))), installing: null, waiting: null });
    await answerWith("9.9.9+next");
    expect(reloads).toEqual(["reload"]);
    page.stop();
  });
});
