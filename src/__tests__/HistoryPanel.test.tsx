// TabXtract - GPL-3.0-or-later. See LICENSE.
import { StrictMode } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { deleteJob, listJobs } from "../api";
import { HistoryPanel } from "../components/HistoryPanel";
import type { Job } from "../types";

vi.mock("../api", () => ({
  listJobs: vi.fn(),
  deleteJob: vi.fn(),
  startAnalyze: vi.fn(),
}));

const listJobsMock = vi.mocked(listJobs);
const deleteJobMock = vi.mocked(deleteJob);

function job(id: string, title: string, status: Job["status"] = "analyzed"): Job {
  return {
    id, title, status,
    source: `/videos/${title}.mp4`, source_kind: "file",
    created_at: 1_700_000_000, updated_at: 1_700_000_000,
    error: null, analysis: null, render: null, output_dir: null,
    local_path: `/videos/${title}.mp4`,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

afterEach(() => {
  vi.resetAllMocks();
});

describe("HistoryPanel", () => {
  it("renders one row per job, with its title and status", async () => {
    listJobsMock.mockResolvedValue([job("a", "first", "rendered"), job("b", "second", "failed")]);

    render(<HistoryPanel onOpenJob={vi.fn()} />);

    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("first")).toBeTruthy();
    expect(within(rows[0]).getByText(/finished/)).toBeTruthy();
    expect(within(rows[1]).getByText(/failed/)).toBeTruthy();
  });

  it("renders nothing when there is no history", async () => {
    listJobsMock.mockResolvedValue([]);

    const { container } = render(<HistoryPanel onOpenJob={vi.fn()} />);

    await waitFor(() => expect(listJobsMock).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
  });

  it("Delete removes the job on the backend and refreshes the list", async () => {
    listJobsMock
      .mockResolvedValueOnce([job("a", "first"), job("b", "second")])
      .mockResolvedValueOnce([job("b", "second")]);
    deleteJobMock.mockResolvedValue({ deleted: "a" });
    const user = userEvent.setup();

    render(<HistoryPanel onOpenJob={vi.fn()} />);
    const firstRow = (await screen.findAllByRole("row"))[0];
    await user.click(within(firstRow).getByRole("button", { name: "Delete" }));

    expect(deleteJobMock).toHaveBeenCalledWith("a");
    await waitFor(() => expect(screen.queryByText("first")).toBeNull());
    expect(listJobsMock).toHaveBeenCalledTimes(2);
    expect(screen.getAllByRole("row")).toHaveLength(1);
  });

  it("unmounting while the query is in flight is harmless", async () => {
    const pending = deferred<Job[]>();
    listJobsMock.mockReturnValue(pending.promise);
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});

    const { unmount } = render(<HistoryPanel onOpenJob={vi.fn()} />);
    unmount();
    await act(async () => pending.resolve([job("a", "late")]));

    expect(errors).not.toHaveBeenCalled();
  });

  // StrictMode (how src/main.tsx mounts the app) runs the effect twice on the
  // same component. Without the effect's cancellation, whichever response
  // arrives last wins, even when it belongs to the discarded first run.
  it("a response from a discarded effect run does not overwrite a newer one", async () => {
    const discarded = deferred<Job[]>();
    const current = deferred<Job[]>();
    listJobsMock.mockReturnValueOnce(discarded.promise).mockReturnValueOnce(current.promise);

    render(
      <StrictMode>
        <HistoryPanel onOpenJob={vi.fn()} />
      </StrictMode>,
    );
    expect(listJobsMock).toHaveBeenCalledTimes(2);

    await act(async () => current.resolve([job("b", "current")]));
    await act(async () => discarded.resolve([job("a", "stale")]));

    expect(screen.getByText("current")).toBeTruthy();
    expect(screen.queryByText("stale")).toBeNull();
  });
});
