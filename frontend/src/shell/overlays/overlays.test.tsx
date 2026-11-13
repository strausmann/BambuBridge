import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test-utils";
import { AppComboBox } from "./AppComboBox";
import { AppDialog } from "./AppDialog";
import { AppSearchField } from "./AppSearchField";
import { AppSheet } from "./AppSheet";
import { useBackClosesOverlay } from "./useBackClosesOverlay";

class FakeViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
  scale = 1;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

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

describe.each(["dialog", "sheet"] as const)("%s", (kind) => {
  it("opens with its title as the name, closes with the close button and with its actions", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Opener kind={kind} />);
    await user.click(screen.getByRole("button", { name: "Öffnen" }));
    const dialog = await screen.findByRole("dialog", { name: "Drucker wählen" });
    expect(dialog).toHaveTextContent("Inhalt");
    await user.click(screen.getByRole("button", { name: "Schließen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.click(screen.getByRole("button", { name: "Öffnen" }));
    await user.click(await screen.findByRole("button", { name: "Übernehmen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("is marked short while the visible part of the page is short (keyboard open)", async () => {
    const viewport = new FakeViewport();
    viewport.height = 380;
    vi.stubGlobal("visualViewport", viewport);
    const user = userEvent.setup();
    renderWithProviders(<Opener kind={kind} />);
    await user.click(screen.getByRole("button", { name: "Öffnen" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.closest("[data-short]")).not.toBeNull();
    act(() => {
      viewport.height = 800;
      viewport.dispatchEvent(new Event("resize"));
    });
    expect(dialog.closest("[data-short]")).toBeNull();
  });

  it("Back closes it and the page stays", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Opener kind={kind} />);
    const before = window.history.length;
    await user.click(screen.getByRole("button", { name: "Öffnen" }));
    await screen.findByRole("dialog");
    expect(window.history.length).toBe(before + 1);
    expect(window.history.state).toMatchObject({ bbOverlay: expect.any(Number) });
    await act(async () => {
      window.history.back();
      await new Promise((resolve) => window.addEventListener("popstate", resolve, { once: true }));
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(window.location.pathname).toBe("/");
  });
});

describe("useBackClosesOverlay", () => {
  function Probe({ open, onClose }: { open: boolean; onClose: () => void }) {
    useBackClosesOverlay(open, onClose);
    return null;
  }

  it("keeps the router's own state in the entry it adds", () => {
    window.history.replaceState({ __TSR_index: 3, key: "abc" }, "", "/device");
    const { unmount } = renderWithProviders(<Probe open onClose={() => {}} />);
    expect(window.history.state).toMatchObject({ __TSR_index: 3, key: "abc", bbOverlay: expect.any(Number) });
    unmount();
  });

  it("closed another way, it takes its entry back out", async () => {
    const back = vi.spyOn(window.history, "back");
    const { rerender } = renderWithProviders(<Probe open onClose={() => {}} />);
    rerender(<Probe open={false} onClose={() => {}} />);
    expect(back).toHaveBeenCalledTimes(1);
    back.mockRestore();
  });

  it("after a navigation away it leaves the history alone", () => {
    const back = vi.spyOn(window.history, "back");
    const { rerender } = renderWithProviders(<Probe open onClose={() => {}} />);
    window.history.pushState({ __TSR_index: 9 }, "", "/protocol");
    rerender(<Probe open={false} onClose={() => {}} />);
    expect(back).not.toHaveBeenCalled();
    back.mockRestore();
  });

  it("a popstate that lands on its own entry again does not close it", () => {
    const onClose = vi.fn();
    renderWithProviders(<Probe open onClose={onClose} />);
    window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("AppComboBox", () => {
  const options = [
    { id: "x1c", label: "X1 Carbon" },
    { id: "p1s", label: "P1S" },
    { id: "a1m", label: "A1 mini" },
  ];

  function Picker() {
    const [value, setValue] = useState<string | null>(null);
    return (
      <>
        <AppComboBox label="Drucker" options={options} selectedKey={value} onSelectionChange={setValue} description="Der Drucker, an den gesendet wird." emptyText="Kein Drucker passt." />
        <p data-testid="value">{value ?? "-"}</p>
      </>
    );
  }

  it("lists matches while typing, picks one, and says when nothing matches", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Picker />);
    const field = screen.getByRole("combobox", { name: "Drucker" });
    expect(field).toHaveAccessibleDescription("Der Drucker, an den gesendet wird.");
    await user.type(field, "P1");
    const listbox = await screen.findByRole("listbox");
    expect(listbox).toHaveTextContent("P1S");
    expect(listbox).not.toHaveTextContent("A1 mini");
    await user.click(screen.getByRole("option", { name: "P1S" }));
    expect(screen.getByTestId("value")).toHaveTextContent("p1s");
    await user.clear(field);
    await user.type(field, "zzz");
    expect(await screen.findByText("Kein Drucker passt.")).toBeInTheDocument();
  });
});

describe("AppSearchField", () => {
  function Search() {
    const [value, setValue] = useState("");
    const [submitted, setSubmitted] = useState("");
    return (
      <>
        <AppSearchField label="Protokoll durchsuchen" value={value} onChange={setValue} onSubmit={setSubmitted} hideLabel />
        <p data-testid="submitted">{submitted}</p>
      </>
    );
  }

  it("types, submits with Enter and clears with its button", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Search />);
    const field = screen.getByRole("searchbox", { name: "Protokoll durchsuchen" });
    expect(field).toHaveAttribute("enterkeyhint", "search");
    await user.type(field, "ams{Enter}");
    expect(screen.getByTestId("submitted")).toHaveTextContent("ams");
    await user.click(screen.getByRole("button", { name: "Suche leeren" }));
    expect(field).toHaveValue("");
  });
});
