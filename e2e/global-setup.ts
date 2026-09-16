// TabXtract - GPL-3.0-or-later. See LICENSE.
//
// Brings up everything the browser test needs: a synthetic video, the real
// sidecar, a Vite build pointed at it and `vite preview` serving that build.
//
// The build is what forces this order: src/backend.ts reads VITE_BACKEND_PORT
// and VITE_BACKEND_TOKEN from import.meta.env, which Vite resolves at build
// time, so the sidecar has to exist before the app is compiled. The build goes
// to a temporary directory, never to dist/: that one is what Tauri packages,
// and this build carries a token inside.
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer, type AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { writeState } from "./state";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const PYTHON = process.env.TABXTRACT_PYTHON ?? "python3";
// server/main.py, TOKEN_HEADER. Not importable from here: it is Python.
const TOKEN_HEADER = "x-tabxtract-token";
const HANDSHAKE_PREFIX = "TABXTRACT_READY ";
const STARTUP_TIMEOUT = 120_000;

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address() as AddressInfo;
      server.close(() => resolve(port));
    });
  });
}

function run(command: string, args: string[], env: NodeJS.ProcessEnv = {}): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: ROOT, env: { ...process.env, ...env } });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", (code) =>
      code === 0
        ? resolve(stdout)
        : reject(new Error(`${command} ${args.join(" ")} exited ${code}\n${stderr.slice(-4000)}`)),
    );
  });
}

async function waitUntil(what: string, probe: () => Promise<boolean>): Promise<void> {
  const deadline = Date.now() + STARTUP_TIMEOUT;
  let lastError = "";
  while (Date.now() < deadline) {
    try {
      if (await probe()) return;
    } catch (error) {
      lastError = String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`${what} did not come up within ${STARTUP_TIMEOUT} ms. ${lastError}`);
}

/** Start `python -m server` and wait for its handshake line and /api/health. */
async function startSidecar(port: number, token: string, dataDir: string, tempDir: string) {
  const child = spawn(PYTHON, ["-m", "server", "--port", String(port), "--token", token], {
    cwd: ROOT,
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env, TABXTRACT_DATA_DIR: dataDir, TMPDIR: tempDir },
  });
  let stderr = "";
  let handshake = "";
  child.stderr.on("data", (chunk) => (stderr += chunk));
  child.stdout.on("data", (chunk) => (handshake += chunk));

  await waitUntil("the sidecar", async () => {
    if (child.exitCode !== null) {
      throw new Error(`the sidecar exited with ${child.exitCode}\n${stderr.slice(-4000)}`);
    }
    if (!handshake.includes(HANDSHAKE_PREFIX)) return false;
    const response = await fetch(`http://127.0.0.1:${port}/api/health`, {
      headers: { [TOKEN_HEADER]: token },
    });
    return response.ok;
  });
  return child;
}

function stop(child: ChildProcess | undefined): void {
  if (!child || child.exitCode !== null) return;
  child.kill("SIGTERM");
}

export default async function globalSetup(): Promise<() => Promise<void>> {
  const root = mkdtempSync(join(tmpdir(), "tabxtract-e2e-"));
  const distDir = join(root, "dist");
  const outputDir = join(root, "pdfs");
  let sidecar: ChildProcess | undefined;
  let preview: ChildProcess | undefined;

  const teardown = async () => {
    stop(preview);
    stop(sidecar);
    rmSync(root, { recursive: true, force: true });
  };

  try {
    const video = JSON.parse(
      await run(PYTHON, ["-m", "tests.synthetic_video", join(root, "paged.mkv")]),
    ) as { path: string; width: number; height: number };

    const backendPort = await freePort();
    const token = `e2e-${Math.random().toString(36).slice(2)}`;
    sidecar = await startSidecar(backendPort, token, join(root, "data"), join(root, "tmp"));

    const api = async (path: string, init: RequestInit = {}) => {
      const response = await fetch(`http://127.0.0.1:${backendPort}${path}`, {
        ...init,
        headers: { [TOKEN_HEADER]: token, "content-type": "application/json" },
      });
      if (!response.ok) throw new Error(`${path} answered ${response.status}: ${await response.text()}`);
      return response.json();
    };

    // The two steps the browser cannot do: there is no file picker and no
    // directory picker outside Tauri. Everything else happens through the UI.
    await api("/api/preferences", { method: "PUT", body: JSON.stringify({ output_dir: outputDir }) });
    const job = (await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ path: video.path }),
    })) as { id: string; title: string };

    await run("npx", ["vite", "build", "--outDir", distDir, "--emptyOutDir"], {
      VITE_BACKEND_PORT: String(backendPort),
      VITE_BACKEND_TOKEN: token,
    });

    const previewPort = await freePort();
    const baseUrl = `http://127.0.0.1:${previewPort}`;
    preview = spawn(
      "npx",
      ["vite", "preview", "--outDir", distDir, "--host", "127.0.0.1",
       "--port", String(previewPort), "--strictPort"],
      { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"] },
    );
    await waitUntil("vite preview", async () => (await fetch(baseUrl)).ok);

    writeState({
      baseUrl,
      backend: { port: backendPort, token },
      tokenHeader: TOKEN_HEADER,
      video: { path: video.path, width: video.width, height: video.height },
      jobId: job.id,
      jobTitle: job.title,
      outputDir,
    });
  } catch (error) {
    await teardown();
    throw error;
  }

  return teardown;
}
