// TabXtract - GPL-3.0-or-later. See LICENSE.
import { useState } from "react";

import { openInSystemViewer, revealInFileManager } from "../desktop";
import type { RenderResult } from "../types";

interface Props {
  render: RenderResult;
}

function scoreClass(score: number): string {
  if (score >= 90) return "score-good";
  if (score >= 60) return "score-warn";
  return "score-bad";
}

export function ResultScreen({ render }: Props) {
  const [copied, setCopied] = useState(false);

  async function copyReport() {
    // The whole render result, as JSON: it is what the extraction failure
    // issue template asks for, and it contains no path outside the output dir.
    try {
      await navigator.clipboard.writeText(JSON.stringify(render, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="screen result-screen">
      <h2>Done</h2>
      <p>
        The PDFs are in <code>{render.output_dir}</code>.
      </p>
      <p>
        <button onClick={() => void revealInFileManager(render.output_dir)}>
          Show in file manager
        </button>
        {render.combined_path && (
          <button className="secondary" onClick={() => void openInSystemViewer(render.combined_path!)}>
            Open combined PDF
          </button>
        )}
        <button className="secondary" onClick={() => void copyReport()}>
          {copied ? "Report copied" : "Copy report"}
        </button>
      </p>

      <p className="hint">
        Read the report before printing: failures in this domain are silent, and a PDF
        missing pages looks just as tidy as a complete one.
      </p>

      <div className="song-reports">
        {render.songs.map((s) => (
          <div key={s.index} className="song-report-card">
            <div className="song-report-header">
              <h3>{s.title}</h3>
              <span className={`score-badge ${scoreClass(s.report.score)}`}>{s.report.score}</span>
            </div>
            <p>{s.pages} A4 page(s)</p>
            <p>{s.report.measure_continuity}</p>
            {s.report.notes.length > 0 && (
              <ul className="report-notes">
                {s.report.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            )}
            <div className="card-actions">
              <button onClick={() => void openInSystemViewer(s.path)}>Open PDF</button>
              <button className="secondary" onClick={() => void revealInFileManager(s.path)}>
                Show in file manager
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
