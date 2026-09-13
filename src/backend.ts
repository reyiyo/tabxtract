// TabXtract - GPL-3.0-or-later. See LICENSE.
//
// Port and token of the local backend. Tauri starts the sidecar, reads its
// handshake from stdout and exposes it through the `backend_info` command; if
// the frontend loads before the sidecar has finished coming up, it arrives
// later through the `backend-ready` event.
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export interface BackendInfo {
  port: number;
  token: string;
}

let current: BackendInfo | null = null;
const waiters: ((info: BackendInfo) => void)[] = [];

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Development fallback: `npm run dev` in the browser, with the sidecar
 *  started by hand (`python -m server`). */
function fromEnv(): BackendInfo | null {
  const port = Number(import.meta.env.VITE_BACKEND_PORT);
  const token = import.meta.env.VITE_BACKEND_TOKEN;
  return port && token ? { port, token } : null;
}

export function backendInfo(): BackendInfo | null {
  return current;
}

export async function initBackend(): Promise<BackendInfo> {
  if (current) return current;

  if (!isTauri()) {
    const env = fromEnv();
    if (!env) {
      throw new Error(
        "No backend: open the app with `npm run tauri dev`, or set " +
          "VITE_BACKEND_PORT and VITE_BACKEND_TOKEN to point at your own sidecar.",
      );
    }
    current = env;
    return current;
  }

  const info = await invoke<BackendInfo | null>("backend_info");
  if (info) {
    current = info;
    return info;
  }

  return new Promise<BackendInfo>((resolve, reject) => {
    waiters.push(resolve);
    const timeout = setTimeout(
      () => reject(new Error("the backend did not respond within 60 seconds")),
      60_000,
    );
    listen<BackendInfo>("backend-ready", (event) => {
      clearTimeout(timeout);
      current = event.payload;
      while (waiters.length) waiters.shift()?.(event.payload);
    });
  });
}

export function backendUrl(path: string): string {
  const info = current;
  if (!info) throw new Error("the backend has not started yet");
  return `http://127.0.0.1:${info.port}${path}`;
}

/** For <img src> and the WebSocket, which cannot send headers. */
export function withToken(path: string): string {
  const info = current;
  if (!info) throw new Error("the backend has not started yet");
  const separator = path.includes("?") ? "&" : "?";
  return backendUrl(`${path}${separator}token=${encodeURIComponent(info.token)}`);
}

export function authHeaders(): Record<string, string> {
  const info = current;
  if (!info) throw new Error("the backend has not started yet");
  return { "X-TabXtract-Token": info.token, "Content-Type": "application/json" };
}
