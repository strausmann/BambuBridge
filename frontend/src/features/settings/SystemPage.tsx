import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { TEXT_LINK } from "../../shell/ui";
import { useInfo } from "../../app/session";
import { useReadiness } from "../common/api";
import { Badge, Card, Code, LoadError, Loading } from "../common/ui";

/** Version and build of the server and the readiness of its parts. */
export function SystemPage() {
  const { t } = useLingui();
  const info = useInfo();
  const readiness = useReadiness();
  return (
    <>
      <Card title={t`Server`} id="server-title">
        {info.isPending ? (
          <Loading />
        ) : info.isError ? (
          <LoadError error={info.error} onRetry={() => void info.refetch()} />
        ) : (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
            <dt className="text-ink-2">{t`Name`}</dt>
            <dd>{info.data.name}</dd>
            <dt className="text-ink-2">{t`Version`}</dt>
            <dd data-testid="server-version">{info.data.version}</dd>
            <dt className="text-ink-2">{t`Build`}</dt>
            <dd className="min-w-0">
              <Code>{info.data.build}</Code>
            </dd>
          </dl>
        )}
      </Card>
      <Card title={t`Zustand`} id="state-title">
        {readiness.isPending ? (
          <Loading />
        ) : readiness.isError ? (
          <LoadError error={readiness.error} onRetry={() => void readiness.refetch()} />
        ) : (
          <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2">
            <dt className="text-ink-2">{t`Datenbank`}</dt>
            <dd>
              <Badge tone={readiness.data.database === "ok" ? "ok" : readiness.data.database === "unknown" ? "neutral" : "bad"}>
                {readiness.data.database === "ok" ? t`In Ordnung` : readiness.data.database === "unknown" ? t`Unbekannt` : t`Nicht erreichbar`}
              </Badge>
            </dd>
            <dt className="text-ink-2">{t`Einstellungen live`}</dt>
            <dd>
              <Badge tone={readiness.data.listener === "ok" ? "ok" : readiness.data.listener === "unknown" ? "neutral" : "bad"}>
                {readiness.data.listener === "ok" ? t`In Ordnung` : readiness.data.listener === "unknown" ? t`Unbekannt` : t`Nicht erreichbar`}
              </Badge>
            </dd>
          </dl>
        )}
      </Card>
      <Card title={t`Weiteres`} id="more-title">
        <ul className="flex flex-col">
          <li>
            <Link to="/device" className={TEXT_LINK}>
              {t`Dieses Gerät: Verbindung, App-Installation und Versionen`}
            </Link>
          </li>
          <li>
            <a href="/docs" className={TEXT_LINK}>
              {t`Beschreibung der Schnittstelle (API)`}
            </a>
          </li>
        </ul>
      </Card>
    </>
  );
}
