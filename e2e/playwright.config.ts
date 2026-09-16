// TabXtract - GPL-3.0-or-later. See LICENSE.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  // Not *.spec.ts: vitest picks that up by default and would try to run these.
  testMatch: /.*\.e2e\.ts$/,
  globalSetup: "./global-setup.ts",
  // A flaky test is worse than no test, so a failure is never retried away.
  retries: 0,
  // One browser against one sidecar with a single processing worker.
  workers: 1,
  fullyParallel: false,
  // Decoding, analysing and rendering a real video is slow by nature.
  timeout: 300_000,
  expect: { timeout: 120_000 },
  reporter: process.env.CI
    ? [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]]
    : [["list"]],
  use: {
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
});
