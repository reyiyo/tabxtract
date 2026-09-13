// TabXtract - GPL-3.0-or-later. See LICENSE.
import { useEffect, useState } from "react";

import { ApiError, createLocalJob, createUrlJob, probeVideo } from "../api";
import { isTauri } from "../backend";
import { onVideoDrop, pickVideoFile } from "../desktop";
import type { VideoInfo } from "../types";

interface Props {
  onJobCreated: (jobId: string) => void;
}

function formatDuration(seconds: number | null): string {
  if (!seconds) return "unknown duration";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatSize(bytes: number | null): string {
  return bytes ? `${(bytes / 1e6).toFixed(0)} MB` : "unknown size";
}

export function SourceScreen({ onJobCreated }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const [url, setUrl] = useState("");
  const [info, setInfo] = useState<VideoInfo | null>(null);
  const [formatId, setFormatId] = useState<string>("");

  async function startLocal(path: string) {
    setBusy(true);
    setError(null);
    try {
      const job = await createLocalJob(path);
      onJobCreated(job.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  useEffect(() => {
    return onVideoDrop((paths) => {
      setDragOver(false);
      void startLocal(paths[0]);
    });
    // startLocal only closes over stable setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleProbe() {
    setBusy(true);
    setError(null);
    setHint("");
    setInfo(null);
    try {
      const probed = await probeVideo(url.trim());
      setInfo(probed);
      setFormatId(probed.formats[0]?.format_id ?? "");
    } catch (e) {
      const err = e as ApiError;
      setError(err.message);
      setHint(err.hint ?? "");
    } finally {
      setBusy(false);
    }
  }

  async function handleDownload() {
    setBusy(true);
    setError(null);
    try {
      const job = await createUrlJob(url.trim(), formatId || null);
      onJobCreated(job.id);
    } catch (e) {
      const err = e as ApiError;
      setError(err.message);
      setHint(err.hint ?? "");
      setBusy(false);
    }
  }

  return (
    <div className="screen source-screen">
      <h1>TabXtract</h1>
      <p className="subtitle">
        Pick a tablature video — guitar, bass, ukulele or drums — and it is rebuilt as a
        printable A4 PDF. All the processing happens on this machine.
      </p>

      <div className="source-columns">
        <section
          className={`dropzone ${dragOver ? "drag-over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => e.preventDefault()}
        >
          <h2>Local file</h2>
          <p>Drop a video here, or pick one with the system file chooser.</p>
          <button
            disabled={busy || !isTauri()}
            onClick={async () => {
              const path = await pickVideoFile();
              if (path) void startLocal(path);
            }}
          >
            Choose file…
          </button>
          {!isTauri() && (
            <p className="hint">The native picker only exists inside the app.</p>
          )}
        </section>

        <section className="url-panel">
          <h2>From a URL</h2>
          <div className="url-row">
            <input
              value={url}
              placeholder="https://…"
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && url.trim()) void handleProbe();
              }}
            />
            <button disabled={busy || !url.trim()} onClick={() => void handleProbe()}>
              Look up
            </button>
          </div>

          {info && (
            <div className="video-info">
              {info.thumbnail && <img src={info.thumbnail} alt="" className="thumb" />}
              <h3>{info.title}</h3>
              <p>
                {info.uploader ?? "unknown author"} · {formatDuration(info.duration)}
              </p>
              <label>
                Quality:
                <select value={formatId} onChange={(e) => setFormatId(e.target.value)}>
                  {info.formats.map((f) => (
                    <option key={f.format_id} value={f.format_id}>
                      {f.height ? `${f.height}p` : f.note || f.format_id} · {f.ext} ·{" "}
                      {formatSize(f.filesize)}
                    </option>
                  ))}
                </select>
              </label>
              <p className="hint">
                By default it downloads the best video-only track up to 1080p: no audio is
                needed and the download is considerably smaller.
              </p>
              <button disabled={busy} onClick={() => void handleDownload()}>
                Download and analyse
              </button>
            </div>
          )}
        </section>
      </div>

      {error && (
        <div className="error">
          <p>{error}</p>
          {hint && <p className="hint">{hint}</p>}
        </div>
      )}
    </div>
  );
}
