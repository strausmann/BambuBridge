import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createQueryClient } from "./app/queryClient";
import { createAppRouter } from "./app/router";
import { installAuthGuard } from "./app/session";
import { initI18n, pickLanguage } from "./i18n";
import "./index.css";
import { applyTheme, readTheme } from "./shell/theme";

async function start() {
  await initI18n(pickLanguage());
  applyTheme(readTheme());
  const queryClient = createQueryClient();
  installAuthGuard(queryClient);
  const router = createAppRouter();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App queryClient={queryClient} router={router} />
    </StrictMode>,
  );
}

void start();
