import { useLingui } from "@lingui/react/macro";
import { useId, type ReactNode } from "react";
import { FIELD } from "../../shell/ui";

export interface TimeRange {
  from: string;
  to: string;
}

/** A labelled native control: the platform's own pickers are the best ones on a phone. */
export function FilterField({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-small font-semibold">
        {label}
      </label>
      {children(id)}
    </div>
  );
}

export function SelectFilter({ label, value, onChange, options, anyLabel }: { label: string; value: string; onChange: (value: string) => void; options: { value: string; label: string }[]; anyLabel: string }) {
  return (
    <FilterField label={label}>
      {(id) => (
        <select id={id} value={value} onChange={(event) => onChange(event.target.value)} className={`${FIELD} appearance-auto`}>
          <option value="">{anyLabel}</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </FilterField>
  );
}

export function TimeRangeFilter({ value, onChange }: { value: TimeRange; onChange: (value: TimeRange) => void }) {
  const { t } = useLingui();
  return (
    <>
      <FilterField label={t`Von`}>
        {(id) => <input id={id} type="datetime-local" value={value.from} onChange={(event) => onChange({ ...value, from: event.target.value })} className={FIELD} />}
      </FilterField>
      <FilterField label={t`Bis`}>
        {(id) => <input id={id} type="datetime-local" value={value.to} onChange={(event) => onChange({ ...value, to: event.target.value })} className={FIELD} />}
      </FilterField>
    </>
  );
}

/** The filters of a list, in a grid that is one column on a phone. */
export function FilterBar({ children, label }: { children: ReactNode; label: string }) {
  return (
    <form role="search" aria-label={label} onSubmit={(event) => event.preventDefault()} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {children}
    </form>
  );
}
