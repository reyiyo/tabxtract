// TabXtract - GPL-3.0-or-later. See LICENSE.
//
// The user's path through the real app in a real browser, against the real
// sidecar: history, progress, review, region editing, render and result.
//
// Two steps happen through the API instead of the UI, because outside Tauri
// the app cannot do them: choosing the video file and choosing the output
// directory. Both are done in the global setup.
import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { readState, type E2EState } from "./state";

// Read lazily, not at import time: listing the tests (`--list`) does not run
// the global setup, and the state file only exists once it has.
let cached: E2EState | undefined;
const state = (): E2EState => (cached ??= readState());

async function api(path: string, init: RequestInit = {}) {
  const { backend, tokenHeader } = state();
  const response = await fetch(`http://127.0.0.1:${backend.port}${path}`, {
    ...init,
    headers: { [tokenHeader]: backend.token, "content-type": "application/json" },
  });
  if (!response.ok) throw new Error(`${path} answered ${response.status}`);
  return response.json();
}

test("a video becomes a printable PDF through the app", async ({ page }) => {
  const { baseUrl, jobId, jobTitle, video, outputDir } = state();

  await page.goto(baseUrl);

  // First run: the notice covers the app until it is dismissed.
  const notice = page.getByRole("heading", { name: "Before you start" });
  await expect(notice).toBeVisible();
  await page.getByRole("button", { name: "Got it" }).click();
  await expect(notice).toBeHidden();

  const row = page.getByRole("row").filter({ hasText: jobTitle });
  await expect(row).toBeVisible();

  // Occupy the single processing worker, so the re-run below is queued behind
  // it: the progress screen is then guaranteed to be reached, and the progress
  // socket subscribes before the run it reports starts. The broker keeps no
  // backlog, so that order matters.
  await api("/api/jobs", { method: "POST", body: JSON.stringify({ path: video.path }) });

  await row.getByRole("button", { name: "Re-run" }).click();

  await expect(page.getByRole("heading", { name: "Analysing the video…" })).toBeVisible();
  await expect(page.locator(".progress-log li").first()).toBeVisible();

  // --- review ------------------------------------------------------------
  await expect(page.getByRole("heading", { name: "Review" })).toBeVisible();
  await expect(page.getByText(/Detected mode:\s*Paged/)).toBeVisible();

  const canvas = page.locator("canvas");
  // The editor only draws once the frame has loaded; until then the canvas
  // keeps its default size.
  await expect
    .poll(async () => canvas.evaluate((element: HTMLCanvasElement) => element.width))
    .toBeGreaterThan(300);

  const analysis = (await api(`/api/jobs/${jobId}`)) as {
    analysis: { region: { bbox: [number, number, number, number] } };
  };
  const [, , detectedX1, detectedY1] = analysis.analysis.region.bbox;
  const box = (await canvas.boundingBox())!;
  // The canvas shows the whole frame, so one video pixel is this many CSS
  // pixels, whatever the window size.
  const perVideoPixel = box.width / video.width;
  const handle = { x: box.x + detectedX1 * perVideoPixel, y: box.y + detectedY1 * perVideoPixel };
  const shrink = 30 * perVideoPixel;

  await page.mouse.move(handle.x, handle.y);
  await page.mouse.down();
  await page.mouse.move(handle.x - shrink, handle.y - shrink, { steps: 10 });
  await page.mouse.up();

  // --- render ------------------------------------------------------------
  await page.getByRole("button", { name: "Generate PDFs" }).click();
  await expect(page.getByRole("heading", { name: "Compositing and laying out…" })).toBeVisible();

  await expect(page.getByRole("heading", { name: "Done" })).toBeVisible();
  await expect(page.getByText(outputDir)).toBeVisible();

  const pageCount = page.getByText(/\d+ A4 page\(s\)/);
  await expect(pageCount).toBeVisible();
  const pages = Number(/(\d+) A4 page/.exec((await pageCount.textContent()) ?? "")?.[1]);
  expect(pages).toBeGreaterThanOrEqual(2);

  // The PDF the screen is talking about exists and is a PDF.
  const rendered = (await api(`/api/jobs/${jobId}/report`)) as {
    songs: { path: string; pages: number }[];
  };
  expect(rendered.songs).toHaveLength(1);
  expect(rendered.songs[0].pages).toBe(pages);
  expect(readFileSync(rendered.songs[0].path).subarray(0, 4).toString()).toBe("%PDF");

  // The drag reached the backend: the region the render used is the edited one.
  const job = (await api(`/api/jobs/${jobId}`)) as {
    overrides: { region: { x1: number; y1: number } };
  };
  expect(job.overrides.region.x1).toBeLessThan(detectedX1);
  expect(job.overrides.region.y1).toBeLessThan(detectedY1);
});
