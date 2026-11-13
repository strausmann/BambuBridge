/**
 * Overlay harness: a sheet and a dialog with a combobox, a second field and the main button at
 * the end, the shape every form overlay of the app has. `?open=sheet|dialog` opens one at once, `?open=combo` shows the combobox alone,
 * `&low=1` puts the combobox last.
 * The keyboard test (harness/keyboard.spec.ts) checks what stays visible on a short viewport.
 */
import { I18nProvider } from "@lingui/react";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { Button, Input, Label, TextField } from "react-aria-components";
import { i18n, initI18n } from "../src/i18n";
import "../src/index.css";
import { AppComboBox } from "../src/shell/overlays/AppComboBox";
import { AppDialog } from "../src/shell/overlays/AppDialog";
import { AppSheet } from "../src/shell/overlays/AppSheet";
import { FIELD, PRIMARY_BUTTON, SECONDARY_BUTTON } from "../src/shell/ui";

const PRINTERS = ["X1 Carbon Werkstatt", "P1S Keller", "A1 mini Büro", "P1P Garage", "X1E Labor", "A1 Wohnzimmer", "H2D Studio", "P2S Dachboden"].map((label, index) => ({ id: `p${index}`, label }));

/** `low`: the combobox comes last, so it can be scrolled to the bottom edge (the list must flip up). */
function Form({ low }: { low: boolean }) {
  const combo = <AppComboBox label="Drucker" options={PRINTERS} emptyText="Kein Drucker passt." description="Name oder Standort des Druckers" />;
  return (
    <>
      <p className="text-ink-2">Die Spule wird diesem Drucker zugewiesen. Die Zuweisung lässt sich jederzeit ändern; der Drucker meldet den Verbrauch danach an Spoolman.</p>
      {low ? null : combo}
      <TextField className="flex flex-col gap-1">
        <Label className="font-semibold">Notiz</Label>
        <Input className={FIELD} />
      </TextField>
      <TextField className="flex flex-col gap-1">
        <Label className="font-semibold">Restgewicht in Gramm</Label>
        <Input className={FIELD} inputMode="decimal" />
      </TextField>
      <p className="text-ink-2">Ohne Drucker bleibt die Spule im Lager. Das Restgewicht wird nur gespeichert, wenn der Drucker selbst keines meldet; ein gemessener Wert ersetzt es beim nächsten Druck.</p>
      {low ? combo : null}
    </>
  );
}

const params = new URLSearchParams(location.search);
const low = params.get("low") === "1";

/** `?open=combo`: only the combobox on the page (its list is the one overlay under test). */
function ComboOnly() {
  return (
    <main className="flex flex-col items-start gap-4 p-4">
      <h1 className="text-title font-bold">Spule 17</h1>
      <AppComboBox label="Drucker" options={PRINTERS} emptyText="Kein Drucker passt." />
    </main>
  );
}

function Page() {
  const initial = params.get("open");
  if (initial === "combo") return <ComboOnly />;
  const [open, setOpen] = useState<"sheet" | "dialog" | null>(initial === "sheet" || initial === "dialog" ? initial : null);
  const close = (isOpen: boolean) => setOpen(isOpen ? open : null);
  const actions = (
    <>
      <Button onPress={() => setOpen(null)} className={SECONDARY_BUTTON}>
        Abbrechen
      </Button>
      <Button onPress={() => setOpen(null)} className={PRIMARY_BUTTON}>
        Übernehmen
      </Button>
    </>
  );
  return (
    <main className="flex flex-col items-start gap-4 p-4">
      <h1 className="text-title font-bold">Spule 17</h1>
      <Button onPress={() => setOpen("sheet")} className={PRIMARY_BUTTON}>
        Drucker zuweisen (Sheet)
      </Button>
      <Button onPress={() => setOpen("dialog")} className={SECONDARY_BUTTON}>
        Drucker zuweisen (Dialog)
      </Button>
      <AppSheet isOpen={open === "sheet"} onOpenChange={close} title="Drucker zuweisen" actions={actions}>
        <Form low={low} />
      </AppSheet>
      <AppDialog isOpen={open === "dialog"} onOpenChange={close} title="Drucker zuweisen" actions={actions}>
        <Form low={low} />
      </AppDialog>
    </main>
  );
}

await initI18n("de");
createRoot(document.getElementById("root")!).render(
  <I18nProvider i18n={i18n}>
    <Page />
  </I18nProvider>,
);
