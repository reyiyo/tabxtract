// TabXtract - GPL-3.0-or-later. See LICENSE.
import { useState } from "react";

import { frameUrl, patchRegion, startRender } from "../api";
import { pickDirectory } from "../desktop";
import type { AnalysisResult, RegionOverride, SongInfo } from "../types";
import { RegionEditor } from "./RegionEditor";

interface Props {
  jobId: string;
  analysis: AnalysisResult;
  outputDir: string | null;
  onOutputDirChange: (dir: string) => void;
  onRenderStarted: () => void;
}

const MODE_LABELS: Record<string, string> = {
  scroll_vertical: "Vertical scroll",
  scroll_horizontal: "Horizontal scroll",
  paginated: "Paged",
};

export function ReviewScreen({
  jobId,
  analysis,
  outputDir,
  onOutputDirChange,
  onRenderStarted,
}: Props) {
  const [region, setRegion] = useState<RegionOverride>({
    x0: analysis.region.bbox[0], y0: analysis.region.bbox[1],
    x1: analysis.region.bbox[2], y1: analysis.region.bbox[3],
  });
  const [songs, setSongs] = useState<SongInfo[]>(
    analysis.songs.map((s) => ({ ...s, title: s.title ?? `Song ${s.index + 1}` }))
  );
  const [profileName, setProfileName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateSong(index: number, patch: Partial<SongInfo>) {
    setSongs((prev) => prev.map((s) => (s.index === index ? { ...s, ...patch } : s)));
  }

  async function handleGenerate() {
    // The output directory is chosen once and remembered between sessions;
    // it is only asked for again when there is none yet.
    let target = outputDir;
    if (!target) {
      target = await pickDirectory(null);
      if (!target) return;
      onOutputDirChange(target);
    }

    setSubmitting(true);
    setError(null);
    try {
      await patchRegion(jobId, { region, songs });
      await startRender(jobId, {
        region,
        songs,
        save_profile_name: profileName || null,
        output_dir: target,
      });
      onRenderStarted();
    } catch (e) {
      setError(String((e as Error).message || e));
      setSubmitting(false);
    }
  }

  return (
    <div className="screen review-screen">
      <h2>Review</h2>

      {analysis.region.low_res_warning && (
        <p className="warning">
          The detected region is under 800px wide, so the result will be poor. If you can,
          find a better source — the same video at a higher resolution.
        </p>
      )}

      <p>
        Detected mode: <strong>{MODE_LABELS[analysis.advance_mode] ?? analysis.advance_mode}</strong>
        {" · "}Likely instrument: <strong>{analysis.region.instrument}</strong>
        {" · "}Region confidence: <strong>{Math.round(analysis.region.confidence * 100)}%</strong>
        {analysis.matched_profile && <> {" · "}Reused profile: <strong>{analysis.matched_profile}</strong></>}
      </p>

      <p className="hint">Drag the rectangle or its corners to correct the region if needed.</p>
      <RegionEditor imageUrl={frameUrl(jobId)} initialRegion={region} onChange={setRegion} />

      <h3>Detected songs ({songs.length})</h3>
      <table className="songs-table">
        <thead>
          <tr><th>#</th><th>Title</th><th>First frame</th><th>Last frame</th></tr>
        </thead>
        <tbody>
          {songs.map((s) => (
            <tr key={s.index}>
              <td>{s.index + 1}</td>
              <td>
                <input value={s.title} onChange={(e) => updateSong(s.index, { title: e.target.value })} />
              </td>
              <td>
                <input type="number" value={s.start_frame}
                       onChange={(e) => updateSong(s.index, { start_frame: Number(e.target.value) })} />
              </td>
              <td>
                <input type="number" value={s.end_frame}
                       onChange={(e) => updateSong(s.index, { end_frame: Number(e.target.value) })} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <label className="profile-input">
        Save this configuration as a profile (optional):
        <input value={profileName} onChange={(e) => setProfileName(e.target.value)}
               placeholder="e.g. songsterr-bass" />
      </label>

      <p className="hint">
        Output folder: <code>{outputDir ?? "asked for when generating"}</code>
      </p>

      {error && <p className="error">{error}</p>}

      <button disabled={submitting} onClick={() => void handleGenerate()}>
        {submitting ? "Generating…" : "Generate PDFs"}
      </button>
    </div>
  );
}
