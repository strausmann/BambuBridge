import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SHORT_VIEWPORT_PX, useVisualViewport } from "./useVisualViewport";

class FakeViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
  scale = 1;
}

function Probe() {
  const viewport = useVisualViewport();
  return <p data-testid="probe" data-short={viewport.short || undefined} data-height={viewport.height ?? ""} />;
}

const root = () => document.documentElement.style;

afterEach(() => {
  vi.unstubAllGlobals();
  root().removeProperty("--vvh");
  root().removeProperty("--vv-top");
});

describe("useVisualViewport", () => {
  it("writes the visible height and offset as --vvh and --vv-top, and follows resize events", () => {
    const viewport = new FakeViewport();
    vi.stubGlobal("visualViewport", viewport);
    render(<Probe />);
    expect(root().getPropertyValue("--vvh")).toBe("800px");
    expect(root().getPropertyValue("--vv-top")).toBe("0px");

    act(() => {
      viewport.height = 412.5;
      viewport.offsetTop = 37;
      viewport.dispatchEvent(new Event("resize"));
    });
    expect(root().getPropertyValue("--vvh")).toBe("412.5px");
    expect(root().getPropertyValue("--vv-top")).toBe("37px");
    expect(screen.getByTestId("probe")).toHaveAttribute("data-short");
    expect(screen.getByTestId("probe")).toHaveAttribute("data-height", "412.5");
  });

  it("follows scrolling of the visual viewport (iOS moves it under the keyboard)", () => {
    const viewport = new FakeViewport();
    vi.stubGlobal("visualViewport", viewport);
    render(<Probe />);
    act(() => {
      viewport.offsetTop = 120;
      viewport.dispatchEvent(new Event("scroll"));
    });
    expect(root().getPropertyValue("--vv-top")).toBe("120px");
  });

  it("short below 560 px, not short at or above it, and never while the page is pinch-zoomed", () => {
    expect(SHORT_VIEWPORT_PX).toBe(560);
    const viewport = new FakeViewport();
    vi.stubGlobal("visualViewport", viewport);
    render(<Probe />);
    const probe = screen.getByTestId("probe");
    act(() => {
      viewport.height = SHORT_VIEWPORT_PX;
      viewport.dispatchEvent(new Event("resize"));
    });
    expect(probe).not.toHaveAttribute("data-short");
    act(() => {
      viewport.height = SHORT_VIEWPORT_PX - 1;
      viewport.dispatchEvent(new Event("resize"));
    });
    expect(probe).toHaveAttribute("data-short");
    act(() => {
      viewport.scale = 2;
      viewport.dispatchEvent(new Event("resize"));
    });
    expect(probe).not.toHaveAttribute("data-short");
    act(() => {
      viewport.scale = 1.005; // rounding of a page that is not zoomed
      viewport.dispatchEvent(new Event("resize"));
    });
    expect(probe).toHaveAttribute("data-short");
  });

  it("stops listening when the last user unmounts", () => {
    const viewport = new FakeViewport();
    const remove = vi.spyOn(viewport, "removeEventListener");
    vi.stubGlobal("visualViewport", viewport);
    const { unmount } = render(<Probe />);
    unmount();
    expect(remove).toHaveBeenCalledWith("resize", expect.any(Function));
    expect(remove).toHaveBeenCalledWith("scroll", expect.any(Function));
  });

  it("without a visual viewport the CSS fallbacks stay in charge", () => {
    vi.stubGlobal("visualViewport", undefined);
    render(<Probe />);
    expect(root().getPropertyValue("--vvh")).toBe("");
    expect(screen.getByTestId("probe")).not.toHaveAttribute("data-short");
    expect(screen.getByTestId("probe")).toHaveAttribute("data-height", "");
  });
});
