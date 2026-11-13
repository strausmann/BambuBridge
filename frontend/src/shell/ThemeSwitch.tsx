import { useLingui } from "@lingui/react/macro";
import { useState, type ReactNode } from "react";
import { Radio, RadioGroup } from "react-aria-components";
import { THUMB_RING } from "../design/tokens";
import { MoonIcon, SunIcon, SystemIcon } from "./icons";
import { isTheme, readTheme, storeTheme, switchTheme, type ThemeChoice } from "./theme";

// The classes of the roles named in THUMB_RING (the pairing the contrast test checks). Written
// out because the stylesheet is built from class names found in the source; a role changed in
// THUMB_RING without its class here does not compile.
const RING_CLASS: Record<typeof THUMB_RING.edge, string> = { "line-strong": "border-line-strong" };
const THUMB_CLASS: Record<typeof THUMB_RING.thumb, string> = { surface: "bg-surface" };
const TRACK_CLASS: Record<typeof THUMB_RING.track, string> = { sunken: "bg-sunken" };

/**
 * System / light / dark, remembered in `localStorage` (`bb.theme`) and set as `data-theme`.
 * The raised thumb slides to the chosen option (transform only); its ring is what makes the
 * chosen state visible (3:1 against the track, `THUMB_RING` in design/tokens.ts); the page itself cross-fades
 * (`switchTheme`). The position comes from `data-choice`, not from an inline style (CSP).
 */
export function ThemeSwitch() {
  const { t } = useLingui();
  const [choice, setChoice] = useState<ThemeChoice>(readTheme);

  const options: { value: ThemeChoice; label: string; icon: ReactNode }[] = [
    { value: "system", label: t`Systemdesign`, icon: <SystemIcon width={18} height={18} /> },
    { value: "light", label: t`Helles Design`, icon: <SunIcon width={18} height={18} /> },
    { value: "dark", label: t`Dunkles Design`, icon: <MoonIcon width={18} height={18} /> },
  ];

  return (
    <RadioGroup
      aria-label={t`Design`}
      orientation="horizontal"
      value={choice}
      data-choice={choice}
      onChange={(value) => {
        if (!isTheme(value)) return;
        setChoice(value);
        storeTheme(value);
        switchTheme(value);
      }}
      className={`group/theme relative flex rounded-r2 p-0.5 ${TRACK_CLASS[THUMB_RING.track]}`}
    >
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute top-0.5 left-0.5 size-11 rounded-r1 border transition-transform duration-200 ease-out group-data-[choice=dark]/theme:translate-x-[200%] group-data-[choice=light]/theme:translate-x-full ${RING_CLASS[THUMB_RING.edge]} ${THUMB_CLASS[THUMB_RING.thumb]}`}
      />
      {options.map((option) => (
        <Radio
          key={option.value}
          value={option.value}
          aria-label={option.label}
          className="press relative flex size-11 cursor-pointer items-center justify-center rounded-r1 text-ink-2 data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-1 data-[focus-visible]:outline-link data-[selected]:text-ink"
        >
          {option.icon}
        </Radio>
      ))}
    </RadioGroup>
  );
}
