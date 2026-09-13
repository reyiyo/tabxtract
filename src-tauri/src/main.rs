// TabXtract - extracts tablature from video and rebuilds it as a PDF.
// Copyright (C) 2026 TabXtract contributors
//
// This program is free software: you can redistribute it and/or modify it
// under the terms of the GNU General Public License as published by the Free
// Software Foundation, either version 3 of the License, or (at your option)
// any later version. See <https://www.gnu.org/licenses/>.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! Desktop shell.
//!
//! Starts the Python backend as a child process, reads the handshake line with
//! the ephemeral port and the token from its stdout, and hands both to the
//! frontend. The child is killed on exit: an orphaned sidecar with opencv
//! inside keeps burning CPU.

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::Serialize;
use tauri::{Emitter, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const HANDSHAKE_PREFIX: &str = "TABXTRACT_READY ";

#[derive(Clone, Debug, Serialize)]
struct BackendInfo {
    port: u16,
    token: String,
}

#[derive(Default)]
struct Backend {
    info: Mutex<Option<BackendInfo>>,
    child: Mutex<Option<CommandChild>>,
}

/// The frontend calls this at startup; when there is no handshake yet it
/// returns `null` and waits for the `backend-ready` event.
#[tauri::command]
fn backend_info(state: State<Backend>) -> Option<BackendInfo> {
    state.info.lock().unwrap().clone()
}

/// Look for an executable on PATH. The system one is preferred over the
/// bundled copy: it tends to be newer, and it is the one the user chose to
/// install.
fn which(program: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        let candidate = dir.join(program);
        if candidate.is_file() {
            return Some(candidate);
        }
        if cfg!(windows) {
            let with_ext = dir.join(format!("{program}.exe"));
            if with_ext.is_file() {
                return Some(with_ext);
            }
        }
    }
    None
}

/// PATH first, otherwise the binary that ships in the bundle.
fn resolve_binary(program: &str, bundled_dir: &Path) -> Option<PathBuf> {
    if let Some(found) = which(program) {
        return Some(found);
    }
    let name = if cfg!(windows) {
        format!("{program}.exe")
    } else {
        program.to_string()
    };
    let bundled = bundled_dir.join(name);
    bundled.is_file().then_some(bundled)
}

/// Bundle resources can lose the executable bit when they are copied.
#[cfg(unix)]
fn ensure_executable(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    if let Ok(metadata) = std::fs::metadata(path) {
        let mut perms = metadata.permissions();
        perms.set_mode(perms.mode() | 0o755);
        let _ = std::fs::set_permissions(path, perms);
    }
}

#[cfg(not(unix))]
fn ensure_executable(_path: &Path) {}

fn parse_handshake(line: &str) -> Option<BackendInfo> {
    let payload = line.trim().strip_prefix(HANDSHAKE_PREFIX)?;
    let parsed: serde_json::Value = serde_json::from_str(payload).ok()?;
    Some(BackendInfo {
        port: parsed.get("port")?.as_u64()? as u16,
        token: parsed.get("token")?.as_str()?.to_string(),
    })
}

fn spawn_sidecar(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let resource_dir = app.path().resource_dir()?;
    let sidecar_dir = resource_dir.join("sidecar").join("tabxtract-server");
    let exe = sidecar_dir.join(if cfg!(windows) {
        "tabxtract-server.exe"
    } else {
        "tabxtract-server"
    });
    if !exe.is_file() {
        return Err(format!("sidecar not found at {}", exe.display()).into());
    }
    ensure_executable(&exe);

    let data_dir = app.path().app_data_dir()?;
    std::fs::create_dir_all(&data_dir)?;
    let native_dir = resource_dir.join("native");

    let mut command = app
        .shell()
        .command(&exe)
        .env("TABXTRACT_DATA_DIR", data_dir.to_string_lossy().to_string())
        .env("TABXTRACT_PARENT_PID", std::process::id().to_string());

    for (var, program) in [
        ("TABEXTRACT_FFMPEG", "ffmpeg"),
        ("TABEXTRACT_FFPROBE", "ffprobe"),
        ("TABEXTRACT_TESSERACT", "tesseract"),
        ("TABXTRACT_YTDLP", "yt-dlp"),
    ] {
        if let Some(found) = resolve_binary(program, &native_dir) {
            command = command.env(var, found.to_string_lossy().to_string());
        }
    }
    let tessdata = native_dir.join("tessdata");
    if tessdata.is_dir() {
        command = command.env("TESSDATA_PREFIX", tessdata.to_string_lossy().to_string());
    }

    let (mut rx, child) = command.spawn()?;
    *app.state::<Backend>().child.lock().unwrap() = Some(child);

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes).to_string();
                    if let Some(info) = parse_handshake(&line) {
                        *handle.state::<Backend>().info.lock().unwrap() = Some(info.clone());
                        let _ = handle.emit("backend-ready", info);
                    }
                }
                CommandEvent::Stderr(bytes) => {
                    // The backend log goes to the app console; it is not sent
                    // anywhere (there is no telemetry).
                    eprint!("[backend] {}", String::from_utf8_lossy(&bytes));
                }
                CommandEvent::Terminated(status) => {
                    let _ = handle.emit("backend-exited", status.code);
                }
                _ => {}
            }
        }
    });

    Ok(())
}

fn kill_sidecar(app: &tauri::AppHandle) {
    if let Some(child) = app.state::<Backend>().child.lock().unwrap().take() {
        let _ = child.kill();
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Backend::default())
        .invoke_handler(tauri::generate_handler![backend_info])
        .setup(|app| {
            if let Err(err) = spawn_sidecar(app.handle()) {
                // Without a backend the app does nothing useful, but the window
                // still has to open so the error can be shown.
                eprintln!("could not start the backend: {err}");
                let _ = app.handle().emit("backend-failed", err.to_string());
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error starting TabXtract");

    app.run(|handle, event| match event {
        // Clean exit and abrupt exit: the child has to be killed in both. On
        // Windows the child outlives the parent, so the sidecar also watches
        // the parent PID on its own.
        RunEvent::ExitRequested { .. } | RunEvent::Exit => kill_sidecar(handle),
        _ => {}
    });
}
