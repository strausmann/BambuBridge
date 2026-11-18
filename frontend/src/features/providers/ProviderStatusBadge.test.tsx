import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../test-utils";
import { ProviderStatusBadge } from "./ProviderStatusBadge";

const status = (state: "stopped" | "starting" | "connected" | "disconnected" | "error" | "needs_secret") => ({ state, message: null, since: "2026-11-17T08:00:00Z" });

describe("ProviderStatusBadge", () => {
  it.each([
    ["connected", "Verbunden", "ok"],
    ["starting", "Startet", "info"],
    ["stopped", "Angehalten", "neutral"],
    ["disconnected", "Getrennt", "warn"],
    ["needs_secret", "Geheimnis fehlt", "warn"],
    ["error", "Fehler", "bad"],
  ] as const)("%s reads as %s (tone %s), as a word and not only as a colour", (state, word, tone) => {
    renderWithProviders(<ProviderStatusBadge instance={{ enabled: true, status: status(state) }} />);
    const badge = screen.getByText(word).closest("[data-tone]");
    expect(badge).toHaveAttribute("data-tone", tone);
    expect(badge?.querySelector("svg")).not.toBeNull();
  });

  it("a switched-off instance is 'deactivated', whatever its last state was", () => {
    renderWithProviders(<ProviderStatusBadge instance={{ enabled: false, status: status("error") }} />);
    expect(screen.getByText("Deaktiviert")).toBeInTheDocument();
    expect(screen.queryByText("Fehler")).not.toBeInTheDocument();
  });
});
