import { useLingui } from "@lingui/react/macro";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "react-aria-components";
import { ApiError, apiFetch, AuthRequiredError } from "../../api/client";
import { useInfo } from "../../app/session";
import { AppSheet } from "../../shell/overlays/AppSheet";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "../../shell/ui";

export interface WorkerStatus {
  supported: boolean;
  registered: boolean;
  active: boolean;
  /** A new version is installed and waits for a reload. */
  waiting: boolean;
  /** This page was loaded through the worker. */
  controlled: boolean;
}

export type DisplayMode = "standalone" | "fullscreen" | "minimal-ui" | "browser";

/** What the page reads from the browser; tests pass their own. */
export interface DeviceEnvironment {
  protocol: string;
  displayMode: DisplayMode;
  platform: "ios" | "other";
  serviceWorker: () => Promise<WorkerStatus>;
}

const SESSION_CHECK_PATH = "/api/v1/auth/session";

function readDisplayMode(): DisplayMode {
  for (const mode of ["standalone", "fullscreen", "minimal-ui"] as const) {
    if (window.matchMedia?.(`(display-mode: ${mode})`).matches) return mode;
  }
  return "browser";
}

async function readWorker(): Promise<WorkerStatus> {
  const container = navigator.serviceWorker as ServiceWorkerContainer | undefined;
  if (!container) return { supported: false, registered: false, active: false, waiting: false, controlled: false };
  const registration = await container.getRegistration();
  return {
    supported: true,
    registered: registration !== undefined,
    active: registration?.active != null,
    waiting: registration?.waiting != null,
    controlled: container.controller !== null,
  };
}

/** iPhone and iPad (iPadOS reports a Mac with touch). */
function readPlatform(): "ios" | "other" {
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
  return ios ? "ios" : "other";
}

function browserEnvironment(): DeviceEnvironment {
  return { protocol: window.location.protocol, displayMode: readDisplayMode(), platform: readPlatform(), serviceWorker: readWorker };
}

type SessionCheck = "signed-in" | "signed-out" | "login-page" | "unreachable" | { status: number };

/**
 * The sign-in path as the API sees it. An ordinary request: when the sign-in is gone, the shell
 * reacts as to any other request (the way out through `/auth/continue`); the 401 and login-page
 * states show only where nothing handles that (no shell around the page).
 */
async function checkSessionPath(): Promise<SessionCheck> {
  try {
    await apiFetch(SESSION_CHECK_PATH);
    return "signed-in";
  } catch (error) {
    if (error instanceof AuthRequiredError) return error.status === 401 && error.code !== "unexpected_content" && error.code !== "login_redirect" ? "signed-out" : "login-page";
    if (error instanceof ApiError) return error.status === 0 ? "unreachable" : { status: error.status };
    throw error;
  }
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 border-t border-line py-3 sm:flex-row sm:gap-4">
      <dt className="shrink-0 text-ink-2 sm:w-48">{label}</dt>
      <dd className="min-w-0 [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

/**
 * `/device`: what this browser makes of BambuBridge. For a report or a check before installing:
 * secure connection, display mode, service worker, the build of the app and of the server, and
 * whether the API answers on its sign-in path.
 */
export function DevicePage({ environment }: { environment?: DeviceEnvironment }) {
  const { t } = useLingui();
  const [env] = useState(() => environment ?? browserEnvironment());
  const [installOpen, setInstallOpen] = useState(false);
  const info = useInfo();
  const worker = useQuery({ queryKey: ["device", "worker"], queryFn: env.serviceWorker, staleTime: 0, gcTime: 0 });
  const session = useQuery({ queryKey: ["device", "session-path"], queryFn: checkSessionPath, staleTime: 0, gcTime: 0, retry: false });

  const displayModes: Record<DisplayMode, string> = {
    standalone: t`Installierte App`,
    fullscreen: t`Vollbild`,
    "minimal-ui": t`Browser (minimale Leiste)`,
    browser: t`Browser-Tab`,
  };

  const https = env.protocol === "https:";
  const workerText = (() => {
    const status = worker.data;
    if (!status) return t`Wird geprüft …`;
    if (!status.supported) return https ? t`Nicht unterstützt` : t`Nicht verfügbar (braucht HTTPS)`;
    if (!status.registered) return t`Nicht registriert`;
    if (status.waiting) return t`Aktiv, eine neue Version wartet`;
    if (status.controlled) return t`Aktiv, diese Seite kommt aus dem Worker`;
    return t`Aktiv ab dem nächsten Laden`;
  })();

  const serverBuild = info.data ? `${info.data.version}+${info.data.build}` : null;
  const sessionText = (() => {
    const result = session.data;
    if (session.isFetching && result === undefined) return t`Wird geprüft …`;
    if (result === "signed-in") return t`Erreichbar, angemeldet`;
    if (result === "signed-out") return t`Erreichbar, nicht angemeldet (401)`;
    if (result === "login-page") return t`Ein Proxy antwortet mit einer Anmeldeseite`;
    if (result === "unreachable") return t`Nicht erreichbar`;
    if (result && typeof result === "object") {
      const status = result.status;
      return t`Fehler ${status}`;
    }
    return t`Wird geprüft …`;
  })();

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="text-title font-bold">{t`Dieses Gerät`}</h1>
        <p className="mt-2 text-ink-2">{t`Wie dieser Browser die BambuBridge sieht. Hilfreich für eine Fehlermeldung oder vor der Installation als App.`}</p>
      </div>

      <dl className="flex flex-col border-b border-line">
        <Fact label={t`HTTPS`}>{https ? t`Ja` : t`Nein`}</Fact>
        <Fact label={t`Darstellung`}>{displayModes[env.displayMode]}</Fact>
        <Fact label={t`Service Worker`}>{workerText}</Fact>
        <Fact label={t`Build dieser App`}>
          <code>{__APP_VERSION__}</code>
        </Fact>
        <Fact label={t`Build des Servers`}>
          {serverBuild ? (
            <>
              <code>{serverBuild}</code>
              {serverBuild !== __APP_VERSION__ ? <span className="mt-1 block text-small text-ink-2">{t`Der Server läuft auf einem anderen Build als diese App.`}</span> : null}
            </>
          ) : info.isError ? (
            t`Unbekannt (Server nicht erreichbar)`
          ) : (
            t`Wird geprüft …`
          )}
        </Fact>
        <Fact label={t`API`}>
          <span className="block">{sessionText}</span>
          <code className="mt-1 block text-small text-ink-2">GET {SESSION_CHECK_PATH}</code>
        </Fact>
      </dl>

      <div className="flex flex-wrap gap-3">
        <Button
          onPress={() => {
            void worker.refetch();
            void session.refetch();
            void info.refetch();
          }}
          className={SECONDARY_BUTTON}
        >
          {t`Erneut prüfen`}
        </Button>
        {env.displayMode === "browser" || env.displayMode === "minimal-ui" ? (
          <Button onPress={() => setInstallOpen(true)} className={PRIMARY_BUTTON}>
            {t`Als App installieren`}
          </Button>
        ) : null}
      </div>

      <AppSheet
        isOpen={installOpen}
        onOpenChange={setInstallOpen}
        title={t`Als App installieren`}
        actions={
          <Button onPress={() => setInstallOpen(false)} className={PRIMARY_BUTTON}>
            {t`Fertig`}
          </Button>
        }
      >
        {env.platform === "ios" ? (
          <ol className="flex list-decimal flex-col gap-2 pl-5">
            <li>{t`Diese Seite in Safari öffnen.`}</li>
            <li>{t`Unten auf „Teilen“ tippen (das Quadrat mit dem Pfeil).`}</li>
            <li>{t`„Zum Home-Bildschirm“ wählen und „Hinzufügen“ tippen.`}</li>
          </ol>
        ) : (
          <ol className="flex list-decimal flex-col gap-2 pl-5">
            <li>{t`Das Browsermenü öffnen (die drei Punkte).`}</li>
            <li>{t`„App installieren“ oder „Zum Startbildschirm hinzufügen“ wählen.`}</li>
          </ol>
        )}
        <p className="text-ink-2">{t`Die installierte App öffnet sich ohne Browserleiste. Daten zeigt sie nur mit Verbindung zum Server.`}</p>
      </AppSheet>
    </div>
  );
}
