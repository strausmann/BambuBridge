import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createQueryClient } from "./app/queryClient";
import { createAppRouter } from "./app/router";
import { installAuthGuard } from "./app/session";
import { startUpdates } from "./app/updates";
import { initI18n, pickLanguage } from "./i18n";
import "./index.css";
import { applyTheme, readTheme } from "./shell/theme";
import { registerSW } from "virtual:pwa-register";

async function start() {
  await initI18n(pickLanguage());
  applyTheme(readTheme());
  const queryClient = createQueryClient();
  installAuthGuard(queryClient);
  // The service worker and the version check (src/app/updates.ts); a browser without service
  // workers (plain http on another host) still gets the version check and its reload.
  startUpdates(registerSW);
  const router = createAppRouter();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App queryClient={queryClient} router={router} />
    </StrictMode>,
  );
}

void start();
