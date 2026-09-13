// TabXtract - GPL-3.0-or-later. See LICENSE.
//
// Automatic updates against the GitHub releases. The manifests are signed
// with the updater key, a locally generated key pair that has nothing to do
// with code signing (which this project does not buy: the binaries ship
// unsigned on purpose).
//
// The user can turn this off in Preferences; with that, the app makes no
// request the user did not ask for.
import { check } from "@tauri-apps/plugin-updater";

import { isTauri } from "./backend";

export async function checkForUpdate(): Promise<void> {
  if (!isTauri()) return;
  try {
    const update = await check();
    if (!update) return;
    const accepted = window.confirm(
      `A new version is available (${update.version}). Download and install it now?\n\n` +
        (update.body ?? ""),
    );
    if (!accepted) return;
    await update.downloadAndInstall();
  } catch (err) {
    // An updater failure must not stop the app from being used.
    console.warn("could not check for updates:", err);
  }
}
