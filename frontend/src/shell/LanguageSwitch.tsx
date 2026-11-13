import { useLingui } from "@lingui/react/macro";
import { Button } from "react-aria-components";
import { changeLanguage, isLang, type Lang } from "../i18n";
import { ICON_BUTTON } from "./ui";

/** One button that names the other language in that language and switches to it. */
export function LanguageSwitch() {
  const { i18n } = useLingui();
  const current: Lang = isLang(i18n.locale) ? i18n.locale : "en";
  const other: Lang = current === "de" ? "en" : "de";
  // Each label is written in the language it switches to, so it is readable in either state.
  const label = other === "de" ? "Auf Deutsch wechseln" : "Switch to English";

  return (
    <Button aria-label={label} lang={other} onPress={() => void changeLanguage(other)} className={`${ICON_BUTTON} text-small font-semibold`}>
      {other.toUpperCase()}
    </Button>
  );
}
