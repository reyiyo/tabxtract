// TabXtract - GPL-3.0-or-later. See LICENSE.
import { cancelJob } from "../api";
import { useProgress } from "../hooks/useProgress";

interface Props {
  jobId: string;
  title: string;
  onCancelled?: () => void;
}

export function ProgressScreen({ jobId, title, onCancelled }: Props) {
  const { latest, log } = useProgress(jobId, true);
  const pct = Math.round((latest?.pct ?? 0) * 100);

  return (
    <div className="screen progress-screen">
      <h2>{title}</h2>
      <div className="progress-bar">
        <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <p>
        {latest?.message ?? "starting…"} {latest ? `(${pct}%)` : ""}
      </p>
      <p className="hint">
        On a long video the decoding alone takes several minutes. You can cancel and
        start over at any point.
      </p>
      <button
        className="secondary"
        onClick={async () => {
          await cancelJob(jobId);
          onCancelled?.();
        }}
      >
        Cancel
      </button>
      <ul className="progress-log">
        {log.slice(-12).map((m, i) => (
          <li key={i}>
            [{m.stage}] {m.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
