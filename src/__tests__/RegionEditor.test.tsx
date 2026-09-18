// TabXtract - GPL-3.0-or-later. See LICENSE.
//
// The editor draws on a <canvas>, which jsdom does not implement: getContext
// returns null, elements measure 0x0 and images never load. Those three are
// stubbed so the component runs, and the tests check its contract -- what
// reaches onChange -- never the pixels.
import { Profiler } from "react";
import { render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RegionEditor } from "../components/RegionEditor";
import type { RegionOverride } from "../types";

// Frame size of tests/synthetic.py. The editor displays it 900px wide, a
// non-integer 0.9375 scale, so screen-to-video rounding is exercised.
const VIDEO_W = 960;
const VIDEO_H = 540;
const SCALE = 900 / VIDEO_W;
const REGION: RegionOverride = { x0: 60, y0: 150, x1: 900, y1: 330 };

class LoadedImage {
  onload: (() => void) | null = null;
  crossOrigin = "";
  naturalWidth = VIDEO_W;
  naturalHeight = VIDEO_H;
  set src(_url: string) {
    setTimeout(() => this.onload?.(), 0);
  }
}

beforeEach(() => {
  const ctx = { drawImage: vi.fn(), fillRect: vi.fn(), strokeRect: vi.fn() };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () => ctx as unknown as CanvasRenderingContext2D,
  );
  // On-screen size equal to the backing store: client coordinates are canvas
  // coordinates, i.e. video coordinates times SCALE.
  vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0, y: 0, left: 0, top: 0, right: 900, bottom: 506, width: 900, height: 506,
    toJSON: () => ({}),
  } as DOMRect);
  vi.stubGlobal("Image", LoadedImage);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function renderLoaded(initialRegion: RegionOverride, onChange = vi.fn()) {
  const view = render(<RegionEditor imageUrl="frame.png" initialRegion={initialRegion} onChange={onChange} />);
  const canvas = view.container.querySelector("canvas")!;
  // The scale is only known once the frame has loaded; before that every
  // hit test runs at scale 1.
  await waitFor(() => expect(canvas.width).toBe(900));
  return { ...view, canvas, onChange };
}

const screenPoint = (x: number, y: number) => ({ clientX: x * SCALE, clientY: y * SCALE });

/** Press at a video-space point, move by a video-space delta, release. */
async function drag(canvas: HTMLCanvasElement, from: [number, number], by: [number, number]) {
  const user = userEvent.setup();
  await user.pointer([
    { keys: "[MouseLeft>]", target: canvas, coords: screenPoint(from[0], from[1]) },
    { target: canvas, coords: screenPoint(from[0] + by[0], from[1] + by[1]) },
    { keys: "[/MouseLeft]", target: canvas, coords: screenPoint(from[0] + by[0], from[1] + by[1]) },
  ]);
}

describe("RegionEditor", () => {
  it("dragging the bottom-right handle reports the new corner in video pixels, once, on release", async () => {
    const { canvas, onChange } = await renderLoaded(REGION);

    await drag(canvas, [REGION.x1, REGION.y1], [-100, -20]);

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ x0: 60, y0: 150, x1: 800, y1: 310 });
  });

  it("dragging a corner past the opposite one yields a normalised region", async () => {
    const { canvas, onChange } = await renderLoaded(REGION);

    await drag(canvas, [REGION.x0, REGION.y0], [900, 250]);

    const region = onChange.mock.calls[0][0] as RegionOverride;
    expect(region.x0).toBeLessThan(region.x1);
    expect(region.y0).toBeLessThan(region.y1);
    expect(region).toEqual({ x0: 900, y0: 330, x1: 960, y1: 400 });
  });

  it("dragging the inside moves the whole region", async () => {
    const { canvas, onChange } = await renderLoaded(REGION);

    await drag(canvas, [400, 240], [-40, 30]);

    expect(onChange).toHaveBeenCalledWith({ x0: 20, y0: 180, x1: 860, y1: 360 });
  });

  it("reports whole pixels even when the screen delta is fractional in video space", async () => {
    const { canvas, onChange } = await renderLoaded(REGION);

    await drag(canvas, [REGION.x1, REGION.y1], [-33.3, -7.7]);

    const region = onChange.mock.calls[0][0] as RegionOverride;
    for (const value of Object.values(region)) expect(Number.isInteger(value)).toBe(true);
  });

  it("does not report anything for a press outside the region or a hover", async () => {
    const { canvas, onChange } = await renderLoaded(REGION);
    const user = userEvent.setup();

    await drag(canvas, [10, 10], [200, 200]);
    await user.pointer([
      { target: canvas, coords: screenPoint(400, 240) },
      { target: canvas, coords: screenPoint(500, 300) },
    ]);

    expect(onChange).not.toHaveBeenCalled();
  });

  it("a new initialRegion discards the user's edit and becomes the drag baseline", async () => {
    const { canvas, onChange, rerender } = await renderLoaded(REGION);
    await drag(canvas, [REGION.x1, REGION.y1], [-100, -20]);
    onChange.mockClear();

    const next: RegionOverride = { x0: 100, y0: 200, x1: 500, y1: 300 };
    rerender(<RegionEditor imageUrl="frame.png" initialRegion={next} onChange={onChange} />);
    await drag(canvas, [next.x1, next.y1], [-100, 0]);

    expect(onChange).toHaveBeenCalledWith({ x0: 100, y0: 200, x1: 400, y1: 300 });
  });

  // Implementation-level on purpose: mirroring the prop during render resets
  // the state in the same commit, while doing it from an effect commits once
  // with the stale region first. The final state is identical either way, so
  // counting commits is the only thing that tells the two apart.
  it("resets to a new initialRegion without committing the stale region first", async () => {
    const onChange = vi.fn();
    const commits = vi.fn();
    const tree = (region: RegionOverride) => (
      <Profiler id="editor" onRender={commits}>
        <RegionEditor imageUrl="frame.png" initialRegion={region} onChange={onChange} />
      </Profiler>
    );
    const { container, rerender } = render(tree(REGION));
    const canvas = container.querySelector("canvas")!;
    await waitFor(() => expect(canvas.width).toBe(900));
    commits.mockClear();

    rerender(tree({ x0: 100, y0: 200, x1: 500, y1: 300 }));

    expect(commits).toHaveBeenCalledTimes(1);
  });
});
