import { useLingui } from "@lingui/react/macro";
import type { ReactNode } from "react";
import { Button } from "react-aria-components";
import { ApiError } from "../../api/client";
import { ErrorNote } from "../../shell/AuthScreen";
import { SECONDARY_BUTTON } from "../../shell/ui";

export function PageTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h1 className="min-w-0 text-title font-bold break-words">{children}</h1>
      {aside}
    </div>
  );
}

/** A titled block of a page. */
export function Card({ title, children, aside, id }: { title: string; children: ReactNode; aside?: ReactNode; id?: string }) {
  return (
    <section aria-labelledby={id} className="min-w-0 rounded-r3 border border-line bg-surface p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id={id} className="min-w-0 text-section font-semibold break-words">
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** What a list says when there is nothing in it; never a blank. */
export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="rounded-r2 bg-sunken px-4 py-6 text-center text-ink-2">{children}</p>;
}

type Tone = "ok" | "info" | "warn" | "bad" | "neutral";

function toneClass(tone: Tone): string {
  switch (tone) {
    case "ok":
      return "bg-ok-soft text-ink";
    case "info":
      return "bg-info-soft text-ink";
    case "warn":
      return "bg-warn-soft text-ink";
    case "bad":
      return "bg-bad-soft text-ink";
    case "neutral":
      return "bg-sunken text-ink-2";
  }
}

/** The mark drawn inside the badge: check, note, triangle, cross, dash. */
function toneShape(tone: Tone): string {
  switch (tone) {
    case "ok":
      return "M3 8.5 6.5 12 13 4.5";
    case "info":
      return "M8 3v6M8 12v.25";
    case "warn":
      return "M8 2 14.5 13.5h-13L8 2ZM8 6.5v3";
    case "bad":
      return "M4 4l8 8M12 4l-8 8";
    case "neutral":
      return "M4 8h8";
  }
}

/** A status as shape and word together, so it does not rest on colour alone. */
export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span data-tone={tone} className={`inline-flex max-w-full items-center gap-1.5 rounded-full px-2.5 py-1 text-small font-semibold ${toneClass(tone)}`}>
      <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="shrink-0">
        <path d={toneShape(tone)} />
      </svg>
      <span className="min-w-0 break-words">{children}</span>
    </span>
  );
}

/** Reads a failed request as one sentence for the person looking at the page. */
export function useErrorText(): (error: unknown) => string {
  const { t } = useLingui();
  return (error) => {
    if (error instanceof ApiError) {
      if (error.status === 0) return t`Der Server ist nicht erreichbar.`;
      if (error.status === 403) return t`Dafür fehlt die Berechtigung.`;
      if (error.status === 429) return t`Zu viele Anfragen. Warte eine Minute und versuche es erneut.`;
      if (error.status === 404) return t`Das gibt es nicht mehr. Lade die Seite neu.`;
      if (error.detail && error.status >= 400 && error.status < 500 && error.status !== 401) return error.detail;
    }
    return t`Etwas ist schiefgegangen.`;
  };
}

/** A failed read with a way to ask again. */
export function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useLingui();
  const text = useErrorText();
  return (
    <div className="flex flex-col items-start gap-3">
      <ErrorNote>{text(error)}</ErrorNote>
      <Button onPress={onRetry} className={SECONDARY_BUTTON}>
        {t`Erneut versuchen`}
      </Button>
    </div>
  );
}

export function Loading() {
  const { t } = useLingui();
  return (
    <p role="status" className="py-4 text-ink-2">
      {t`Lädt …`}
    </p>
  );
}

/** A value that may be long and unbroken (a type name, an address): wraps instead of widening the page. */
export function Code({ children }: { children: ReactNode }) {
  return <code className="font-mono text-small break-all">{children}</code>;
}

/** Raw data, scrollable inside its own box so a long value cannot widen the page. */
export function DataBlock({ children, label }: { children: string; label: string }) {
  return (
    // A scrollable box must be reachable with the keyboard, or its overflow cannot be read.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <pre tabIndex={0} aria-label={label} className="max-h-72 overflow-auto rounded-r2 bg-sunken p-3 font-mono text-small break-all whitespace-pre-wrap">
      {children}
    </pre>
  );
}
