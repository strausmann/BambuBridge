/**
 * Layout harness: the whole app with the API answered inside the page.
 * `?state=signed-in` shows the shell, anything else the sign-in; `&path=/x` picks the route;
 * `&signout=fail` lets the sign-out fail with a 503.
 */
import { createMemoryHistory } from "@tanstack/react-router";
import { createRoot } from "react-dom/client";
import { App } from "../src/App";
import { createQueryClient } from "../src/app/queryClient";
import { createAppRouter } from "../src/app/router";
import { initI18n } from "../src/i18n";
import "../src/index.css";

const params = new URLSearchParams(location.search);
const signedIn = params.get("state") === "signed-in";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

window.fetch = (input, init) => {
  const path = String(input);
  if (path === "/api/v1/admin/api-keys" && init?.method === "POST") {
    return Promise.resolve(json({ token: "bb_pat_HarnessTokenHarnessTokenHarnessTokenHarnessTokenHarnessToken0123456789" }, 201));
  }
  if (path === "/api/v1/info") return Promise.resolve(json({ name: "BambuBridge", version: "0.2.0", build: "harness" }));
  if (path === "/api/v1/auth/session" && init?.method === "DELETE" && params.get("signout") === "fail") {
    return Promise.resolve(json({ title: "Database unavailable", status: 503, error_code: "database_unavailable" }, 503));
  }
  if (path === "/api/v1/auth/session" && signedIn) {
    return Promise.resolve(json({ kind: "session", scope: "admin", user: "Wilhelmina Featherstonehaugh-Cholmondeley", csrf_token: "harness" }));
  }
  return Promise.resolve(json({ title: "Authentication required", status: 401, error_code: "not_authenticated" }, 401));
};

await initI18n("de");
const history = createMemoryHistory({ initialEntries: [params.get("path") ?? "/"] });
createRoot(document.getElementById("root")!).render(<App queryClient={createQueryClient()} router={createAppRouter({ history })} />);
