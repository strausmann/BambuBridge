import { useLingui } from "@lingui/react/macro";
import { useState, type ReactNode } from "react";
import { Radio, RadioGroup } from "react-aria-components";
import { MoonIcon, SunIcon, SystemIcon } from "./icons";
import { isTheme, readTheme, storeTheme, switchTheme, type ThemeChoice } from "./theme";

/**
 * System / light / dark, remembered in `localStorage` (`bb.theme`) and set as `data-theme`.
 * The raised thumb slides to the chosen option (transform only); the page itself cross-fades
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
      className="group/theme relative flex rounded-r2 bg-sunken p-0.5"
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute top-0.5 left-0.5 size-11 rounded-r1 bg-surface transition-transform duration-200 ease-out group-data-[choice=dark]/theme:translate-x-[200%] group-data-[choice=light]/theme:translate-x-full"
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
