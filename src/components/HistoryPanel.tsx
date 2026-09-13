// TabXtract - GPL-3.0-or-later. See LICENSE.
import { deleteJob, listJobs, startAnalyze } from "../api";
import { useEffect, useState } from "react";

import { revealInFileManager } from "../desktop";
import type { Job } from "../types";

interface Props {
  onOpenJob: (jobId: string) => void;
}

const STATUS_LABELS: Record<string, string> = {
  new: "new",
  ready: "ready to analyse",
  downloading: "downloading",
  queued: "queued",
  analyzing: "analysing",
  analyzed: "analysed",
  queued_render: "queued",
  rendering: "generating",
  rendered: "finished",
  cancelled: "cancelled",
  failed: "failed",
};

/** Persistent history in SQLite: what makes it possible to re-run a job
 *  without hunting for the video again. */
export function HistoryPanel({ onOpenJob }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);

  async function refresh() {
    setJobs(await listJobs());
  }

  // The fetch lives inside the effect, and the state lands in the promise
  // callback rather than in the effect body: setting state synchronously in an
  // effect costs an extra render pass. `cancelled` covers the panel being
  // unmounted while the query is still in flight.
  useEffect(() => {
    let cancelled = false;
    void listJobs().then((rows) => {
      if (!cancelled) setJobs(rows);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!jobs.length) return null;

  return (
    <div className="history">
      <h2>History</h2>
      <table>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>
                <strong>{job.title}</strong>
                <span className="hint"> · {STATUS_LABELS[job.status] ?? job.status}</span>
              </td>
              <td>{new Date(job.created_at * 1000).toLocaleString()}</td>
              <td className="card-actions">
                {job.status === "rendered" && job.output_dir && (
                  <>
                    <button onClick={() => onOpenJob(job.id)}>View report</button>
                    <button
                      className="secondary"
                      onClick={() => void revealInFileManager(job.output_dir!)}
                    >
                      Folder
                    </button>
                  </>
                )}
                <button
                  className="secondary"
                  onClick={async () => {
                    await startAnalyze(job.id);
                    onOpenJob(job.id);
                  }}
                >
                  Re-run
                </button>
                <button
                  className="secondary"
                  onClick={async () => {
                    await deleteJob(job.id);
                    await refresh();
                  }}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">
        Re-running analyses the original video again. If it came from a URL it is
        downloaded again: the intermediate files are deleted when each job finishes.
      </p>
    </div>
  );
}
