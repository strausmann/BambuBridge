import { useLingui } from "@lingui/react/macro";
import { Button, Input, Label, SearchField } from "react-aria-components";
import { CloseIcon, SearchIcon } from "../icons";
import { FIELD, FOCUS } from "../ui";

export interface AppSearchFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit?: (value: string) => void;
  /** The label is read out but not shown, where the page heading already says what is searched. */
  hideLabel?: boolean;
}

/** A search field: 16 px text (no zoom on iOS), a "search" return key, a 44 px clear button. */
export function AppSearchField({ label, value, onChange, onSubmit, hideLabel }: AppSearchFieldProps) {
  const { t } = useLingui();
  return (
    <SearchField value={value} onChange={onChange} onSubmit={onSubmit} className="group flex flex-col gap-1">
      <Label className={hideLabel ? "sr-only" : "font-semibold"}>{label}</Label>
      <div className="relative">
        <span aria-hidden="true" className="pointer-events-none absolute top-0 left-0 flex size-11 items-center justify-center text-ink-3">
          <SearchIcon />
        </span>
        <Input className={`${FIELD} pr-12 pl-11 [&::-webkit-search-cancel-button]:hidden`} enterKeyHint="search" autoComplete="off" />
        <Button aria-label={t`Suche leeren`} className={`press absolute top-0 right-0 flex size-11 items-center justify-center rounded-r2 text-ink-2 group-data-[empty]:hidden ${FOCUS}`}>
          <CloseIcon />
        </Button>
      </div>
    </SearchField>
  );
}
