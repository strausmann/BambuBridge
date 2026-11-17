import { useLingui } from "@lingui/react/macro";
import { Tab, TabList, TabPanel, Tabs } from "react-aria-components";
import { FOCUS } from "../../shell/ui";
import { PageTitle } from "../common/ui";
import { CommunicationPage } from "./CommunicationPage";
import { EventsPage } from "./EventsPage";

const TAB = `press flex min-h-11 cursor-default items-center border-b-2 border-transparent px-4 font-semibold text-ink-2 data-[hovered]:text-ink data-[selected]:border-primary data-[selected]:text-ink ${FOCUS}`;

export function ProtocolPage() {
  const { t } = useLingui();
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <PageTitle>{t`Protokoll`}</PageTitle>
      <Tabs>
        <TabList aria-label={t`Protokollbereiche`} className="mb-4 flex border-b border-line">
          <Tab id="events" className={TAB}>
            {t`Ereignisse`}
          </Tab>
          <Tab id="communication" className={TAB}>
            {t`Kommunikation`}
          </Tab>
        </TabList>
        <TabPanel id="events">
          <EventsPage />
        </TabPanel>
        <TabPanel id="communication">
          <CommunicationPage />
        </TabPanel>
      </Tabs>
    </div>
  );
}
