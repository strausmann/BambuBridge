/** Shared control styles. Every tappable control is at least 44 px high (touch target). */

export const FOCUS = "data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

export const PRIMARY_BUTTON = `press inline-flex h-11 items-center justify-center gap-2 rounded-r2 bg-primary px-5 font-semibold text-primary-ink hover:bg-primary-hover data-[disabled]:opacity-60 ${FOCUS}`;

/** May wrap to two lines on a narrow screen (a long label), so the height is a minimum. */
export const SECONDARY_BUTTON = `press inline-flex min-h-11 items-center justify-center gap-2 rounded-r2 border border-line-strong bg-surface px-5 py-2 text-center font-semibold text-ink hover:bg-sunken data-[disabled]:opacity-60 ${FOCUS}`;

export const ICON_BUTTON = `press flex size-11 items-center justify-center rounded-r2 text-ink-2 hover:bg-sunken hover:text-ink ${FOCUS}`;

export const FIELD = `h-11 w-full rounded-r2 border border-line-strong bg-surface px-3 text-ink placeholder:text-ink-3 ${FOCUS}`;

/** A link on a line of its own: 44 px high, so it is a full touch target. */
export const TEXT_LINK = "press inline-flex min-h-11 items-center rounded-r1 text-link underline underline-offset-2 hover:text-ink";
