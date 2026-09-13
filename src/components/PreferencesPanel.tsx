// TabXtract - GPL-3.0-or-later. See LICENSE.
import { useEffect, useState } from "react";

import { health, importProfiles, listProfiles, savePreferences, updateYtdlp, ytdlpStatus } from "../api";
import type { Health } from "../api";
import { appVersion, openExternal, pickDirectory, revealInFileManager } from "../desktop";
import type { LayoutProfile, Preferences, YtdlpStatus } from "../types";

interface Props {
  preferences: Preferences;
  onChange: (prefs: Preferences) => void;
  onClose: () => void;
}

export function PreferencesPanel({ preferences, onChange, onClose }: Props) {
  const [ytdlp, setYtdlp] = useState<YtdlpStatus | null>(null);
  const [profiles, setProfiles] = useState<LayoutProfile[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState<string>("");
  const [status, setStatus] = useState<Health | null>(null);

  useEffect(() => {
    void ytdlpStatus().then(setYtdlp).catch(() => setYtdlp(null));
    void listProfiles().then(setProfiles).catch(() => setProfiles([]));
    void appVersion().then(setVersion);
    void health().then(setStatus).catch(() => setStatus(null));
  }, []);

  async function patch(update: Partial<Preferences>) {
    onChange(await savePreferences(update));
  }

  async function handleUpdateYtdlp() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await updateYtdlp();
      setYtdlp(result);
      setMessage(`yt-dlp updated (${result.version ?? "unknown version"}).`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function exportProfiles() {
    // No cloud: profiles are exchanged as a JSON file attached to an issue.
    const blob = new Blob([JSON.stringify(profiles, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "tabxtract-profiles.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  async function handleImport(file: File) {
    try {
      const parsed = JSON.parse(await file.text());
      const result = await importProfiles(parsed);
      setProfiles(await listProfiles());
      setMessage(`Imported: ${result.imported.join(", ") || "none"}.`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal preferences">
        <h2>Preferences</h2>

        <section>
          <h3>Output folder</h3>
          <p className="path">{preferences.output_dir ?? "not chosen yet"}</p>
          <button
            onClick={async () => {
              const dir = await pickDirectory(preferences.output_dir);
              if (dir) await patch({ output_dir: dir });
            }}
          >
            Change…
          </button>
        </section>

        <section>
          <h3>Downloads</h3>
          <label>
            Default maximum quality:
            <select
              value={preferences.youtube_max_height}
              onChange={(e) => void patch({ youtube_max_height: Number(e.target.value) })}
            >
              {[2160, 1440, 1080, 720, 480].map((h) => (
                <option key={h} value={h}>
                  {h}p
                </option>
              ))}
            </select>
          </label>
          <p>
            yt-dlp: {ytdlp?.available ? ytdlp.version : "not available"}
            {ytdlp?.path && <span className="path"> · {ytdlp.path}</span>}
          </p>
          <p className="hint">
            YouTube breaks yt-dlp every so often. If a download fails for no apparent
            reason, update it before reporting the problem.
          </p>
          <button disabled={busy} onClick={() => void handleUpdateYtdlp()}>
            Update yt-dlp
          </button>
        </section>

        <section>
          <h3>App updates</h3>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={preferences.updates_enabled}
              onChange={(e) => void patch({ updates_enabled: e.target.checked })}
            />
            Check for updates on startup
          </label>
          <p className="hint">
            This is the only outbound request the app makes on its own. With it off, it
            contacts no server unless you ask it to.
          </p>
        </section>

        <section>
          <h3>Layout profiles ({profiles.length})</h3>
          <p className="hint">
            A profile remembers the region and advance mode for one video source, matched
            by exact resolution. They are JSON files: shareable through an issue.
          </p>
          <div className="card-actions">
            <button onClick={exportProfiles} disabled={!profiles.length}>
              Export
            </button>
            <label className="button-like">
              Import…
              <input
                type="file"
                accept="application/json"
                style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleImport(file);
                }}
              />
            </label>
          </div>
        </section>

        <section>
          <h3>About</h3>
          <p>
            TabXtract {version || "…"}
            {status?.version && <span className="path"> · engine {status.version}</span>}
          </p>
          <p className="hint">
            Reporting a problem? The bug report form asks for the app version above and
            for the log file, <code>tabxtract.log</code>, which lives in the data folder.
          </p>
          <div className="card-actions">
            <button
              disabled={!status}
              onClick={() => status && void revealInFileManager(status.log_path)}
            >
              Open data folder
            </button>
            <button
              className="secondary"
              onClick={() => void openExternal("https://github.com/reyiyo/tabxtract/issues/new/choose")}
            >
              Report a problem
            </button>
          </div>
        </section>

        {message && <p className="message">{message}</p>}
        <button className="secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
