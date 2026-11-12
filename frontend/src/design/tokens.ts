/**
 * Semantic design tokens as a typed object: the single source for the contrast test.
 * `tokens.test.ts` asserts that `tokens.css` carries exactly these values and that
 * `tokens.css` starts with a verbatim copy of `docs/brand/tokens.css`.
 */

export type Role = "bg" | "surface" | "sunken" | "line" | "line-strong" | "ink" | "ink-2" | "ink-3" | "primary" | "primary-hover" | "primary-ink" | "primary-soft" | "link" | "accent" | "accent-hover" | "accent-ink" | "accent-soft" | "ok" | "ok-soft" | "warn" | "warn-soft" | "bad" | "bad-soft" | "info" | "info-soft";

export type Semantic = Record<Role, string>;

export const themes: { light: Semantic; dark: Semantic } = {
  light: {
    bg: "#F3F7FB",
    surface: "#FBFEFF",
    sunken: "#E9EDF1",
    line: "#D6DDE6",
    "line-strong": "#767D84",
    ink: "#20262C",
    "ink-2": "#4B5259",
    "ink-3": "#5F656D",
    primary: "#006E99",
    "primary-hover": "#00597B",
    "primary-ink": "#FFFFFF",
    "primary-soft": "#D9F1FF",
    link: "#006E99",
    accent: "#A1376E",
    "accent-hover": "#812F58",
    "accent-ink": "#FFFFFF",
    "accent-soft": "#FFE3EF",
    ok: "#00704E",
    "ok-soft": "#DAF6E9",
    warn: "#8C5007",
    "warn-soft": "#FFE9D4",
    bad: "#B02B27",
    "bad-soft": "#FFE7E4",
    info: "#006E99",
    "info-soft": "#D9F1FF",
  },
  dark: {
    bg: "#0D1218",
    surface: "#161C23",
    sunken: "#1E252C",
    line: "#2A3138",
    "line-strong": "#6C7680",
    ink: "#F0F4F7",
    "ink-2": "#C3C8CE",
    "ink-3": "#9FA5AC",
    primary: "#4FB9EB",
    "primary-hover": "#83D1F9",
    "primary-ink": "#042939",
    "primary-soft": "#0B3547",
    link: "#83D1F9",
    accent: "#F183B6",
    "accent-hover": "#FDA8CD",
    "accent-ink": "#3C1628",
    "accent-soft": "#4C1E34",
    ok: "#5ED8A9",
    "ok-soft": "#103627",
    warn: "#FCB26F",
    "warn-soft": "#442910",
    bad: "#FF958A",
    "bad-soft": "#4A231F",
    info: "#83D1F9",
    "info-soft": "#0B3547",
  },
};

/** Radii 6 / 10 / 14 px (keys are the `--radius-<key>` suffix). */
export const radii = { r1: "6px", r2: "10px", r3: "14px" } as const;

/**
 * Every text colour with every surface it is set on. Each pair must reach WCAG AA (4.5:1) in
 * both themes; a new combination in a component belongs in this table first.
 */
export const TEXT_PAIRS: readonly (readonly [text: Role, surface: Role])[] = [
  ["ink", "bg"], ["ink", "surface"], ["ink", "sunken"],
  ["ink-2", "bg"], ["ink-2", "surface"], ["ink-2", "sunken"],
  ["ink-3", "bg"], ["ink-3", "surface"], ["ink-3", "sunken"],
  ["link", "bg"], ["link", "surface"], ["link", "sunken"],
  ["primary", "bg"], ["primary", "surface"], ["primary", "primary-soft"],
  ["primary-ink", "primary"], ["primary-ink", "primary-hover"],
  ["accent", "bg"], ["accent", "surface"], ["accent", "accent-soft"],
  ["accent-ink", "accent"], ["accent-ink", "accent-hover"],
  ["ok", "bg"], ["ok", "surface"], ["ok", "ok-soft"],
  ["warn", "bg"], ["warn", "surface"], ["warn", "warn-soft"],
  ["bad", "bg"], ["bad", "surface"], ["bad", "bad-soft"],
  ["info", "bg"], ["info", "surface"], ["info", "info-soft"],
  ["ink", "primary-soft"], ["ink", "accent-soft"], ["ink", "ok-soft"], ["ink", "warn-soft"], ["ink", "bad-soft"], ["ink", "info-soft"],
];

/** Non-text edges that must stay visible (WCAG 1.4.11, 3:1): the border of an input on each surface. */
export const EDGE_PAIRS: readonly (readonly [edge: Role, surface: Role])[] = [
  ["line-strong", "bg"], ["line-strong", "surface"], ["line-strong", "sunken"],
];

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
}

/** WCAG 2.x contrast ratio between two `#RRGGBB` colours (1 … 21). */
export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}
