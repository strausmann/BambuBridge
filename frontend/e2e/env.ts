/** The server under test (`backend/tests/e2e_app.py`); it listens on the loopback interface only. */
export const PORT = Number(process.env.E2E_PORT ?? 8765);
export const BASE_URL = `http://127.0.0.1:${PORT}`;

/**
 * The bootstrap key of this run: made at random by playwright.config.ts and handed to the server
 * and to the tests through `E2E_BOOTSTRAP_KEY`. Empty when a spec is loaded without that
 * configuration; the tests then fail at the first use instead of trying a guessable key.
 */
export const BOOTSTRAP_KEY = process.env.E2E_BOOTSTRAP_KEY ?? "";
export const BOOTSTRAP_HEADER = "X-BambuBridge-Bootstrap";
export const RESET_PATH = "/__e2e/reset";
/** The reset path answers only with this header (same as in `backend/tests/e2e_app.py`). */
export const RESET_HEADERS = { "X-BambuBridge-E2E": "reset" };
