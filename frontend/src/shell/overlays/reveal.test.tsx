import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test-utils";
import { AppComboBox } from "./AppComboBox";
import { AppDialog } from "./AppDialog";
import { AppSheet } from "./AppSheet";

// Its own file: React Aria remembers module-wide whether a text field had the focus, and that
// decides whether it waits for an on-screen keyboard before it reveals an overlay.

/**
 * A stand-in for the browser's CSS transitions, enough for React Aria's enter and exit. As in a
 * browser, `getAnimations()` returns the transitions still running on the element (here: one is
 * started when none runs), and `cancel()` rejects `finished`. `finishAll()` ends every transition
 * still running.
 */
class FakeTransition {
  playState = "running";
  finished: Promise<void>;
  private settle!: (ok: boolean) => void;
  constructor(readonly element: Element) {
    this.finished = new Promise<void>((resolve, reject) => {
      this.settle = (ok) => (ok ? resolve() : reject(new DOMException("cancelled", "AbortError")));
    });
    this.finished.catch(() => {});
    running.add(this);
  }
  static of(element: Element): FakeTransition[] {
    const live = [...running].filter((transition) => transition.element === element);
    return live.length > 0 ? live : [new FakeTransition(element)];
  }
  cancel() {
    if (!running.delete(this)) return;
    this.playState = "idle";
    this.settle(false);
  }
  finish() {
    if (!running.delete(this)) return;
    this.playState = "finished";
    this.settle(true);
  }
}
const running = new Set<FakeTransition>();
const finishAll = () => [...running].forEach((transition) => transition.finish());

function Opener({ kind }: { kind: "dialog" | "sheet" }) {
  const [open, setOpen] = useState(false);
  const Overlay = kind === "dialog" ? AppDialog : AppSheet;
  return (
    <>
      <button onClick={() => setOpen(true)}>Öffnen</button>
      <Overlay isOpen={open} onOpenChange={setOpen} title="Drucker wählen" actions={<button onClick={() => setOpen(false)}>Übernehmen</button>}>
        <p>Inhalt</p>
      </Overlay>
    </>
  );
}

beforeEach(() => {
  // A touch device (React Aria then waits two frames before it reveals an overlay) whose browser
  // animates overlays.
  Object.defineProperty(Navigator.prototype, "maxTouchPoints", { configurable: true, get: () => 5 });
  vi.stubGlobal("CSSTransition", FakeTransition);
  Element.prototype.getAnimations = function (this: Element) {
    return FakeTransition.of(this) as unknown as Animation[];
  };
  queued.clear();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    nextFrameId += 1;
    queued.set(nextFrameId, callback);
    return nextFrameId;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    queued.delete(id);
  });
});

afterEach(() => {
  finishAll();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(Element.prototype, "getAnimations");
  Reflect.deleteProperty(Navigator.prototype, "maxTouchPoints");
  window.history.replaceState(null, "", "/");
});

// Animation frames run only when the test says so: the reveal comes exactly when the test wants.
// Ids only ever grow, as in a browser, so a cancel can never hit a later request.
const queued = new Map<number, FrameRequestCallback>();
let nextFrameId = 0;
const frames = (count: number) =>
  act(async () => {
    for (let i = 0; i < count; i += 1) {
      const due = [...queued];
      queued.clear();
      for (const [, callback] of due) callback(performance.now());
    }
    await Promise.resolve();
  });

describe.each(["dialog", "sheet"] as const)("%s closed before it is revealed", (kind) => {
  it("by Back: it still closes once it was revealed (it does not stay on screen half-way out)", async () => {
    renderWithProviders(<Opener kind={kind} />);
    fireEvent.click(screen.getByRole("button", { name: "Öffnen" }));
    expect(screen.getByRole("dialog", { name: "Drucker wählen" })).toBeInTheDocument();
    expect(window.history.state).toMatchObject({ bbOverlay: expect.any(Number) });

    // Back at once, before the two frames of the reveal.
    await act(async () => {
      window.history.back();
      await new Promise((resolve) => window.addEventListener("popstate", resolve, { once: true }));
    });
    await frames(4);
    await waitFor(() => {
      finishAll();
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });

  it("by its own button: the same", async () => {
    renderWithProviders(<Opener kind={kind} />);
    fireEvent.click(screen.getByRole("button", { name: "Öffnen" }));
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    await frames(4);
    await waitFor(() => {
      finishAll();
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });

  it("opened and left open, it stays open and is revealed", async () => {
    renderWithProviders(<Opener kind={kind} />);
    fireEvent.click(screen.getByRole("button", { name: "Öffnen" }));
    await frames(4);
    finishAll();
    await frames(2);
    expect(screen.getByRole("dialog", { name: "Drucker wählen" })).toBeInTheDocument();
  });

  it("reopened while it leaves, it closes again at once (it was revealed already)", async () => {
    renderWithProviders(<Opener kind={kind} />);
    fireEvent.click(screen.getByRole("button", { name: "Öffnen" }));
    await frames(4);
    finishAll();
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    // Still leaving: reopened, then closed again.
    expect(screen.getByRole("dialog", { name: "Drucker wählen" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Öffnen", hidden: true }));
    fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
    await waitFor(() => {
      finishAll();
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });
});

describe("combo box list closed before it is revealed", () => {
  const options = [{ id: "a", label: "P1S Keller" }];
  const listbox = () => screen.queryByRole("listbox", { hidden: true });

  // With a text field in focus React Aria waits for an on-screen keyboard that never comes here (up
  // to 600 ms of real time). Without focus it reveals after the two frames the test controls; that
  // is the window under test, and the e2e spec covers the one with the keyboard.
  beforeEach(() => {
    vi.spyOn(document, "hasFocus").mockReturnValue(false);
  });

  it("by Escape: it leaves at once, it does not stay on screen half-way out", async () => {
    renderWithProviders(<AppComboBox label="Drucker" options={options} emptyText="Leer" />);
    const field = screen.getByRole("combobox", { name: "Drucker" });
    // Focus opens the list (menuTrigger "focus"); it is hidden until its frames have run.
    await act(async () => field.focus());
    expect(listbox()).not.toBeNull();

    fireEvent.keyDown(field, { key: "Escape" });
    await frames(4);
    await waitFor(() => {
      finishAll();
      expect(listbox()).toBeNull();
    });
  });

  it("after it was revealed it leaves through its exit animation", async () => {
    renderWithProviders(<AppComboBox label="Drucker" options={options} emptyText="Leer" />);
    const field = screen.getByRole("combobox", { name: "Drucker" });
    await act(async () => field.focus());
    await frames(4);
    finishAll();
    await frames(2);
    expect(listbox()).not.toBeNull();

    fireEvent.keyDown(field, { key: "Escape" });
    // Revealed: the exit animation is running, the list is still there until it ends.
    expect(listbox()).not.toBeNull();
    await waitFor(() => {
      finishAll();
      expect(listbox()).toBeNull();
    });
  });

  it("opened again after it was closed unrevealed, it is revealed and stays", async () => {
    renderWithProviders(<AppComboBox label="Drucker" options={options} emptyText="Leer" />);
    const field = screen.getByRole("combobox", { name: "Drucker" });
    await act(async () => field.focus());
    fireEvent.keyDown(field, { key: "Escape" });
    await frames(4);
    expect(listbox()).toBeNull();

    fireEvent.keyDown(field, { key: "ArrowDown" });
    await frames(4);
    finishAll();
    await frames(2);
    expect(listbox()).not.toBeNull();
  });
});
