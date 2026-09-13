// TabXtract - GPL-3.0-or-later. See LICENSE.
//
// Handshake parsing lives on its own so it can be tested without booting the
// Tauri runtime. The version that runs in production is the Rust one
// (src-tauri/src/main.rs); this covers the same contract from the frontend
// side, which is where it can be tested cheaply.
import type { BackendInfo } from "./backend";

export const HANDSHAKE_PREFIX = "TABXTRACT_READY ";

export function parseHandshake(line: string): BackendInfo | null {
  if (!line.startsWith(HANDSHAKE_PREFIX)) return null;
  try {
    const parsed = JSON.parse(line.slice(HANDSHAKE_PREFIX.length));
    if (typeof parsed.port !== "number" || typeof parsed.token !== "string") return null;
    return { port: parsed.port, token: parsed.token };
  } catch {
    return null;
  }
}
