// TabXtract - GPL-3.0-or-later. See LICENSE.
//
// What the global setup hands to the test. It is a file rather than a bag of
// environment variables because the state is structured; its path travels in
// an environment variable, which the setup can set because Playwright's
// workers do inherit them. The file lives inside the run's temporary
// directory, so nothing is left behind and two runs never collide.
import { readFileSync, writeFileSync } from "node:fs";

export const STATE_ENV = "TABXTRACT_E2E_STATE";

export interface E2EState {
  /** Where `vite preview` serves the built app. */
  baseUrl: string;
  /** The sidecar the build was compiled against. */
  backend: { port: number; token: string };
  /** Header name, read from server/main.py rather than written by hand. */
  tokenHeader: string;
  video: { path: string; width: number; height: number };
  /** Job created through the API: the browser cannot open a file picker. */
  jobId: string;
  jobTitle: string;
  outputDir: string;
}

export function writeState(path: string, state: E2EState): void {
  writeFileSync(path, JSON.stringify(state, null, 2));
  process.env[STATE_ENV] = path;
}

export function readState(): E2EState {
  const path = process.env[STATE_ENV];
  if (!path) throw new Error(`${STATE_ENV} is not set: the global setup did not run`);
  return JSON.parse(readFileSync(path, "utf8")) as E2EState;
}
