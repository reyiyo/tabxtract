// TabXtract - GPL-3.0-or-later. See LICENSE.
//
// Wrappers around the native APIs. Outside Tauri (browser development) each
// one degrades to something harmless instead of breaking the screen.
import { open } from "@tauri-apps/plugin-dialog";
import { openPath, openUrl, revealItemInDir } from "@tauri-apps/plugin-opener";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { getVersion } from "@tauri-apps/api/app";

import { isTauri } from "./backend";

export const VIDEO_EXTENSIONS = ["mp4", "mkv", "webm", "mov", "avi"];

/** Native file picker. Returns the path, not a File: the backend opens the
 *  file from disk and there is no upload at all. */
export async function pickVideoFile(): Promise<string | null> {
  if (!isTauri()) return null;
  const selected = await open({
    multiple: false,
    directory: false,
    filters: [{ name: "Video", extensions: VIDEO_EXTENSIONS }],
  });
  return typeof selected === "string" ? selected : null;
}

export async function pickDirectory(defaultPath?: string | null): Promise<string | null> {
  if (!isTauri()) return null;
  const selected = await open({
    multiple: false,
    directory: true,
    defaultPath: defaultPath ?? undefined,
  });
  return typeof selected === "string" ? selected : null;
}

/** The app version, for the "About" section and bug reports. */
export async function appVersion(): Promise<string> {
  if (!isTauri()) return "dev";
  try {
    return await getVersion();
  } catch {
    return "unknown";
  }
}

/** Open a link in the system browser. The capability limits it to this
 *  project's GitHub pages; outside Tauri a plain new tab does the job. */
export async function openExternal(url: string): Promise<void> {
  if (!isTauri()) {
    window.open(url, "_blank", "noopener");
    return;
  }
  await openUrl(url);
}

export async function openInSystemViewer(path: string): Promise<void> {
  if (!isTauri()) return;
  await openPath(path);
}

/** "Show in Finder / Explorer". */
export async function revealInFileManager(path: string): Promise<void> {
  if (!isTauri()) return;
  await revealItemInDir(path);
}

/**
 * Native drag & drop. The HTML5 drop event does not expose the file path
 * inside the webview, so Tauri's own webview event has to be used.
 */
export function onVideoDrop(handler: (paths: string[]) => void): () => void {
  if (!isTauri()) return () => {};
  const unlisten = getCurrentWebview().onDragDropEvent((event) => {
    if (event.payload.type !== "drop") return;
    const videos = event.payload.paths.filter((p) =>
      VIDEO_EXTENSIONS.includes((p.split(".").pop() ?? "").toLowerCase()),
    );
    if (videos.length) handler(videos);
  });
  return () => {
    void unlisten.then((fn) => fn());
  };
}
