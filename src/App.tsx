// TabXtract - GPL-3.0-or-later. See LICENSE.
import { useCallback, useEffect, useState } from "react";

import { getJob, getPreferences, health, savePreferences } from "./api";
import { initBackend } from "./backend";
import { HistoryPanel } from "./components/HistoryPanel";
import { LegalNotice } from "./components/LegalNotice";
import { PreferencesPanel } from "./components/PreferencesPanel";
import { ProgressScreen } from "./components/ProgressScreen";
import { ResultScreen } from "./components/ResultScreen";
import { ReviewScreen } from "./components/ReviewScreen";
import { SourceScreen } from "./components/SourceScreen";
import { checkForUpdate } from "./updater";
import type { Job, Preferences } from "./types";
import "./App.css";

const ACTIVE_STATUSES = new Set([
  "new",
  "ready",
  "downloading",
  "queued",
  "analyzing",
  "queued_render",
  "rendering",
]);

export default function App() {
  const [ready, setReady] = useState(false);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [showPreferences, setShowPreferences] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    (async () => {
      try {
        await initBackend();
        const [prefs, status] = await Promise.all([getPreferences(), health()]);
        setPreferences(prefs);
        if (status.missing_binaries.length) {
          setWarnings(status.missing_binaries);
        }
        setReady(true);
        if (prefs.updates_enabled) void checkForUpdate();
      } catch (e) {
        setStartupError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  // The job state is polled alongside the WebSocket: the socket carries the
  // progress, this carries the result and survives the socket dropping.
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const fresh = await getJob(jobId);
        if (!cancelled) setJob(fresh);
      } catch {
        // The job may not exist yet right after it is created.
      }
    };
    void tick();
    const interval = setInterval(() => {
      if (!job || ACTIVE_STATUSES.has(job.status)) void tick();
    }, 1500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [jobId, job]);

  const reset = useCallback(() => {
    setJobId(null);
    setJob(null);
  }, []);

  async function acknowledgeNotice() {
    setPreferences(await savePreferences({ legal_notice_acknowledged: true }));
  }

  if (startupError) {
    return (
      <div className="screen">
        <h2>The backend did not start</h2>
        <p className="error">{startupError}</p>
        <p className="hint">
          The engine runs as a separate process inside the app. If this keeps happening,
          open an issue with the console log.
        </p>
      </div>
    );
  }

  if (!ready || !preferences) {
    return (
      <div className="screen">
        <p>Starting the engine…</p>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <button className="link" onClick={reset}>
          TabXtract
        </button>
        <div className="spacer" />
        <button className="secondary" onClick={() => setShowPreferences(true)}>
          Preferences
        </button>
      </header>

      {!preferences.legal_notice_acknowledged && (
        <LegalNotice onAccept={() => void acknowledgeNotice()} />
      )}

      {showPreferences && (
        <PreferencesPanel
          preferences={preferences}
          onChange={setPreferences}
          onClose={() => setShowPreferences(false)}
        />
      )}

      {warnings.length > 0 && (
        <p className="warning">
          Missing binaries: {warnings.join(", ")}.{" "}
          {warnings.includes("tesseract")
            ? "Without tesseract the bar-number check is lost; everything else works."
            : "Without ffmpeg no video can be decoded."}
        </p>
      )}

      <main>{renderBody()}</main>
    </div>
  );

  function renderBody() {
    if (!jobId || !job) {
      return (
        <>
          <SourceScreen onJobCreated={setJobId} />
          <HistoryPanel onOpenJob={setJobId} />
        </>
      );
    }

    if (job.status === "failed") {
      return (
        <div className="screen">
          <h2>Something went wrong</h2>
          <p className="error">{job.error}</p>
          <button onClick={reset}>Start over</button>
        </div>
      );
    }

    if (job.status === "cancelled") {
      return (
        <div className="screen">
          <h2>Job cancelled</h2>
          <button onClick={reset}>Start over</button>
        </div>
      );
    }

    if (job.status === "rendered" && job.render) {
      return (
        <>
          <ResultScreen render={job.render} />
          <button className="reset-button" onClick={reset}>
            Process another video
          </button>
        </>
      );
    }

    if (job.status === "analyzed" && job.analysis) {
      return (
        <ReviewScreen
          jobId={jobId}
          analysis={job.analysis}
          outputDir={preferences?.output_dir ?? null}
          onOutputDirChange={(dir) =>
            setPreferences((prev) => (prev ? { ...prev, output_dir: dir } : prev))
          }
          onRenderStarted={() =>
            setJob((prev) => (prev ? { ...prev, status: "queued_render" } : prev))
          }
        />
      );
    }

    if (job.status === "downloading") {
      return <ProgressScreen jobId={jobId} title="Downloading the video…" onCancelled={reset} />;
    }

    if (job.status === "queued_render" || job.status === "rendering") {
      return (
        <ProgressScreen jobId={jobId} title="Compositing and laying out…" onCancelled={reset} />
      );
    }

    return <ProgressScreen jobId={jobId} title="Analysing the video…" onCancelled={reset} />;
  }
}
