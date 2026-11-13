import { useSyncExternalStore } from "react";
import { subscribeVersionMismatch } from "../api/client";
import { hasDirtyForms } from "./dirtyGuard";

/**
 * Keeping an open page on the build the server runs.
 *
 * Every API answer carries `X-BambuBridge-Version`. When it differs from this page's build, the
 * service worker is asked for the new version and the page reloads into it, once per server
 * version: `sessionStorage["bb.reloadedFor"]` remembers every version a reload was made for (a
 * JSON list), so a page that still comes up on the old build (a cache in between) does not
 * reload in a loop; it shows the banner instead. At most `MAX_RELOADS_PER_SESSION` reloads happen
 * per tab session: two replicas on different builds behind one proxy would otherwise alternate
 * the page between them for ever. Someone typing (a focused field) or a form with unsaved changes also
 * gets the banner ("Neue Version – jetzt neu laden") rather than a reload under their hands.
 *
 * A new worker waits (`registerType: "prompt"`): an open tab would otherwise lose the old hashed
 * files it still loads lazily. It takes over only on this reload, never by itself.
 */

/** What `registerSW` from `virtual:pwa-register` looks like to us, so tests can stand in for it. */
export type RegisterSW = (options: {
  immediate?: boolean;
  onNeedRefresh?: () => void;
  onRegisteredSW?: (swUrl: string, registration: ServiceWorkerRegistration | undefined) => void;
  onRegisterError?: (error: unknown) => void;
}) => (reloadPage?: boolean) => Promise<void>;

export interface UpdateEnvironment {
  storage: Pick<Storage, "getItem" | "setItem">;
  reload: () => void;
  /** Someone is typing or a form holds unsaved changes. */
  isBusy: () => boolean;
  /** How long to wait for a new worker that is still installing before reloading without it. */
  waitForWorkerMs: number;
  /** How long a version signal waits for the worker registration (none comes without support). */
  waitForRegistrationMs: number;
  /** Resolves once the waiting worker controls the page (or after a while, whichever is first). */
  waitForController: () => Promise<void>;
}

export const RELOAD_GUARD_KEY = "bb.reloadedFor";
export const MAX_RELOADS_PER_SESSION = 2;
export const UPDATE_CHECK_INTERVAL_MS = 30 * 60 * 1000;

/** Input types someone types into; a focused checkbox, slider or button is no reason to wait. */
const TEXT_ENTRY_TYPES = new Set(["text", "search", "email", "url", "tel", "password", "number"]);

function typing(): boolean {
  const element = document.activeElement;
  if (!(element instanceof HTMLElement)) return false;
  if (element.isContentEditable || element instanceof HTMLTextAreaElement) return true;
  return element instanceof HTMLInputElement && TEXT_ENTRY_TYPES.has(element.type);
}

/** The versions a reload was made for in this tab session. An entry from before the list format is one version. */
function reloadedFor(storage: UpdateEnvironment["storage"]): string[] {
  const raw = storage.getItem(RELOAD_GUARD_KEY);
  if (raw === null) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.filter((entry): entry is string => typeof entry === "string");
  } catch {
    // not JSON: the earlier single-version format
  }
  return [raw];
}

/** The new worker announces itself with `controllerchange`; a reload before that would get the old one. */
function controllerChange(ms = 3000): Promise<void> {
  return new Promise((resolve) => {
    const container = navigator.serviceWorker as ServiceWorkerContainer | undefined;
    const done = () => {
      container?.removeEventListener("controllerchange", done);
      window.clearTimeout(timer);
      resolve();
    };
    const timer = window.setTimeout(done, ms);
    container?.addEventListener("controllerchange", done);
  });
}

const defaults = (): UpdateEnvironment => ({
  storage: window.sessionStorage,
  reload: () => window.location.reload(),
  isBusy: () => typing() || hasDirtyForms(),
  waitForWorkerMs: 10_000,
  waitForRegistrationMs: 10_000,
  waitForController: () => controllerChange(),
});

interface UpdateState {
  /** A newer version is there but was not applied (someone is typing, or a reload did not help). */
  banner: boolean;
  /** A new worker is installed and waits for the page to reload. */
  waiting: boolean;
}

let state: UpdateState = { banner: false, waiting: false };
let env: UpdateEnvironment | null = null;
let registration: ServiceWorkerRegistration | undefined;
let updateSW: ((reloadPage?: boolean) => Promise<void>) | null = null;
let applying = false;
/** Resolves once `registerSW` reported the registration (or failed): see `whenRegistered`. */
let registeredSignal: Promise<void> = Promise.resolve();
let markRegistered: () => void = () => undefined;
const stateListeners = new Set<() => void>();
const waitingListeners = new Set<() => void>();

function setState(patch: Partial<UpdateState>): void {
  state = { ...state, ...patch };
  stateListeners.forEach((listener) => listener());
}

/** Ask the server for a new worker; a failure (offline, server gone) is not an error here. */
function checkForUpdate(): Promise<void> {
  return registration?.update().then(
    () => undefined,
    () => undefined,
  ) ?? Promise.resolve();
}

function waitForWaitingWorker(ms: number): Promise<boolean> {
  if (state.waiting) return Promise.resolve(true);
  return new Promise((resolve) => {
    const done = (found: boolean) => {
      waitingListeners.delete(onWaiting);
      window.clearTimeout(timer);
      resolve(found);
    };
    const onWaiting = () => done(true);
    const timer = window.setTimeout(() => done(false), ms);
    waitingListeners.add(onWaiting);
  });
}

/**
 * The registration, once `registerSW` has reported it. Right after a deployment the old worker
 * serves the shell, and the first API answer can name the new version before that callback ran:
 * without this wait the update check would find no registration and the update would be lost.
 * Gives up after `waitForRegistrationMs` (a browser without workers never calls back).
 */
function whenRegistered(ms: number): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, ms);
    void registeredSignal.then(() => {
      window.clearTimeout(timer);
      resolve();
    });
  });
}

/**
 * Reload into the newest version: through the waiting worker when there is one (it is told to
 * take over, and the page reloads once it controls the page), otherwise a plain reload, which
 * loads the server's files directly. The reload is made here, not left to the plugin: a worker
 * found by `registration.update()` counts as "external" to workbox-window, which then does not
 * reload by itself.
 *
 * `automatic`: the reload was not asked for. Fetching and installing the worker takes a moment;
 * if someone started typing or changed a form meanwhile, the banner asks instead. From the
 * banner's own button the reload goes ahead regardless: that is the person's choice.
 */
export async function applyUpdate({ automatic = false }: { automatic?: boolean } = {}): Promise<void> {
  if (env === null || applying) return;
  applying = true;
  await whenRegistered(env.waitForRegistrationMs);
  await checkForUpdate();
  if (registration?.installing) await waitForWaitingWorker(env.waitForWorkerMs);
  if (automatic && env.isBusy()) {
    applying = false;
    setState({ banner: true });
    return;
  }
  if (state.waiting && updateSW) {
    const controlled = env.waitForController();
    await updateSW(true);
    await controlled;
  }
  env.reload();
}

async function onServerVersion(version: string): Promise<void> {
  if (env === null) return;
  const done = reloadedFor(env.storage);
  if (done.includes(version) || done.length >= MAX_RELOADS_PER_SESSION || env.isBusy()) {
    // The reload for this version was made already, the reloads of this session are used up,
    // or it would interrupt someone: ask instead.
    void checkForUpdate();
    setState({ banner: true });
    return;
  }
  env.storage.setItem(RELOAD_GUARD_KEY, JSON.stringify([...done, version]));
  await applyUpdate({ automatic: true });
}

/** Registers the worker and starts watching for new versions. Returns a function that stops. */
export function startUpdates(register: RegisterSW, overrides: Partial<UpdateEnvironment> = {}): () => void {
  env = { ...defaults(), ...overrides };
  registeredSignal = new Promise((resolve) => {
    markRegistered = resolve;
  });
  updateSW = register({
    immediate: true,
    onNeedRefresh() {
      setState({ waiting: true });
      [...waitingListeners].forEach((listener) => listener());
    },
    onRegisteredSW(_url, registered) {
      registration = registered;
      markRegistered();
    },
    onRegisterError() {
      markRegistered();
    },
  });
  const onVisibility = () => {
    if (document.visibilityState === "visible") void checkForUpdate();
  };
  document.addEventListener("visibilitychange", onVisibility);
  const timer = window.setInterval(() => void checkForUpdate(), UPDATE_CHECK_INTERVAL_MS);
  const unsubscribe = subscribeVersionMismatch((signal) => void onServerVersion(signal.actual));
  return () => {
    document.removeEventListener("visibilitychange", onVisibility);
    window.clearInterval(timer);
    unsubscribe();
  };
}

export function useUpdateState(): UpdateState {
  return useSyncExternalStore(
    (listener) => {
      stateListeners.add(listener);
      return () => void stateListeners.delete(listener);
    },
    () => state,
  );
}

/** The worker registration, for the device page. */
export function currentRegistration(): ServiceWorkerRegistration | undefined {
  return registration;
}

export function resetUpdatesForTest(): void {
  env = null;
  registration = undefined;
  updateSW = null;
  applying = false;
  registeredSignal = Promise.resolve();
  markRegistered = () => undefined;
  waitingListeners.clear();
  setState({ banner: false, waiting: false });
}
