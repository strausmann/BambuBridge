/** The server under test (`backend/tests/e2e_app.py`); it listens on the loopback interface only. */
export const PORT = Number(process.env.E2E_PORT ?? 8765);
export const BASE_URL = `http://127.0.0.1:${PORT}`;

/** Same text as `E2E_BOOTSTRAP_KEY` in `backend/tests/e2e_app.py`: readable, not a secret. */
export const BOOTSTRAP_KEY = "e2e-bootstrap-key-for-browser-tests-only";
export const BOOTSTRAP_HEADER = "X-BambuBridge-Bootstrap";
export const RESET_PATH = "/__e2e/reset";
