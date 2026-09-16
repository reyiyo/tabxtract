// TabXtract - GPL-3.0-or-later. See LICENSE.
//
// What the global setup hands to the test. It travels through a file rather
// than the environment: Playwright runs the tests in separate worker
// processes, which never see variables the setup defined.
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export interface E2EState {
  /** Where `vite preview` serves the built app. */
  baseUrl: string;
  /** The sidecar the build was compiled against. */
  backend: { port: number; token: string };
  /** Header name from server/main.py (TOKEN_HEADER). */
  tokenHeader: string;
  video: { path: string; width: number; height: number };
  /** Job created through the API: the browser cannot open a file picker. */
  jobId: string;
  jobTitle: string;
  outputDir: string;
}

export const STATE_PATH = join(tmpdir(), "tabxtract-e2e-state.json");

export function writeState(state: E2EState): void {
  writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
}

export function readState(): E2EState {
  return JSON.parse(readFileSync(STATE_PATH, "utf8")) as E2EState;
}
