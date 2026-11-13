import type { Page } from "@playwright/test";
import { expect, shot, signedInAt, test } from "./fixtures";

/** Every visible control below 44×44 px and every visible input below 16 px text. */
async function offenders(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    // Visually hidden on purpose (react-aria's dismiss buttons for screen readers, `.sr-only`):
    // clipped to nothing, so no finger can reach it and none needs to.
    const clippedAway = (el: Element | null): boolean => {
      for (let node = el; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.clipPath === "inset(50%)" || style.clip === "rect(0px, 0px, 0px, 0px)") return true;
      }
      return false;
    };
    const visible = (el: Element) => {
      const box = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return box.width > 0 && box.height > 0 && style.visibility !== "hidden" && !clippedAway(el) && !el.closest("[aria-hidden='true']") && !el.closest(".sr-only");
    };
    const name = (el: Element) => `${el.tagName.toLowerCase()} "${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 40)}"`;
    for (const el of document.querySelectorAll("button, a, [role=tab]")) {
      if (!visible(el)) continue;
      const box = el.getBoundingClientRect();
      if (box.width < 44 - 0.5 || box.height < 44 - 0.5) out.push(`${name(el)} ${Math.round(box.width)}×${Math.round(box.height)}`);
    }
    for (const el of document.querySelectorAll("input, textarea, select")) {
      if (!visible(el)) continue;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (size < 16) out.push(`${name(el)} font-size ${size}px`);
    }
    return out;
  });
}

test("phone: every control is a 44 px touch target and every field has 16 px text", async ({ page }) => {
  await page.goto("/sign-in");
  await expect(page.getByLabel("API-Token")).toBeVisible();
  expect(await offenders(page), "/sign-in").toEqual([]);

  await signedInAt(page, "/");
  for (const path of ["/", "/providers", "/protocol", "/settings", "/device"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await offenders(page), path).toEqual([]);
  }

  // The device page with its sheet open.
  await page.getByRole("button", { name: "Als App installieren" }).click();
  await expect(page.getByRole("dialog", { name: "Als App installieren" })).toBeVisible();
  // Measured once the sheet has arrived, not while it still scales in.
  await page.waitForFunction(() => document.getAnimations().every((animation) => animation.playState !== "running"));
  expect(await offenders(page), "/device with the install sheet").toEqual([]);
  await page.getByRole("button", { name: "Fertig" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await shot(page, "device", { fullPage: true });
});
