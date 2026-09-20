# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""TabXtract's local API.

It listens on 127.0.0.1 only and requires the handshake token the sidecar
emits at startup. Without the token, any page open in the user's browser could
send jobs to this process.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import json
import secrets
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from tabextract.binaries import missing_binaries
from tabextract.profiles import Profile, load_profiles

from . import config, db, runner, ytdlp
from .progress import broker
from .schemas import (
    LocalJobRequest,
    PreferencesPatch,
    ProbeRequest,
    ProfileImportRequest,
    ProfileIn,
    RegionPatchRequest,
    RenderRequest,
    UrlJobRequest,
)

# The engine's version is the app's version; scripts/check_versions.py keeps
# the four declarations in sync, so reading one of them is reading all.
try:
    VERSION = importlib.metadata.version("tabextract")
except importlib.metadata.PackageNotFoundError:  # running from a bare checkout
    VERSION = "0.0.0+dev"
TOKEN_HEADER = "x-tabxtract-token"
ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi"}

# Job ids are uuid4 hex (db.new_job_id). They also name the job's temporary
# directory, so anything else -- ".." for one -- is refused before it gets there.
JobId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{32}$")]


class TokenMiddleware:
    """The handshake, in pure ASGI so it covers the WebSocket too.

    Starlette's `BaseHTTPMiddleware` does not see websocket connections, and
    the progress WS is exactly the route a local attacker would want to
    listen to. The token travels in a header where it can, and in the query
    string on the routes the browser consumes directly (<img src>), which
    cannot send headers.
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http" and scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)  # CORS preflight
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        supplied = headers.get(TOKEN_HEADER)
        if supplied is None:
            query = scope.get("query_string", b"").decode()
            for part in query.split("&"):
                key, _, value = part.partition("=")
                if key == "token":
                    supplied = value

        if supplied is None or not secrets.compare_digest(supplied.encode(), self.token.encode()):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4401})
            else:
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body",
                            "body": b'{"detail":"invalid token"}'})
            return
        await self.app(scope, receive, send)


def create_app(token: str) -> FastAPI:
    app = FastAPI(title="TabXtract", version=VERSION)
    # The frontend runs on tauri://localhost (or Vite's dev server). What
    # protects this process is the token, not the origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TokenMiddleware, token=token)
    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:  # noqa: C901 - it is a flat router

    @app.on_event("startup")
    async def _startup() -> None:
        db.init()
        broker.bind_loop(asyncio.get_running_loop())

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        runner.shutdown()

    # --------------------------------------------------------------- health

    @app.get("/api/health")
    async def health():
        return {
            "ok": True,
            "version": VERSION,
            "data_dir": str(config.app_data_dir()),
            "log_path": str(config.log_path()),
            "missing_binaries": missing_binaries(),
        }

    # ---------------------------------------------------------- preferences

    @app.get("/api/preferences")
    async def get_preferences():
        return config.load_preferences()

    @app.put("/api/preferences")
    async def put_preferences(patch: PreferencesPatch):
        return config.save_preferences(patch.model_dump(exclude_none=True))

    # ------------------------------------------------------------------ jobs

    @app.get("/api/jobs")
    async def list_jobs(limit: Annotated[int, Query(ge=1, le=500)] = 50):
        return db.list_jobs(limit)

    @app.post("/api/jobs")
    async def create_local_job(req: LocalJobRequest):
        path = Path(req.path).expanduser()
        if not path.is_file():
            raise HTTPException(400, f"no such file: {path}")
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                400, f"unsupported format: {path.suffix or '(no extension)'}. "
                     f"Use {', '.join(sorted(ALLOWED_EXTENSIONS))}")
        job_id = db.new_job_id()
        job = db.create_job(job_id, source=str(path), source_kind="file",
                            title=path.stem, status="ready", local_path=str(path))
        runner.submit_analyze(job_id)
        return job

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: JobId):
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return job

    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: JobId):
        runner.request_cancel(job_id)
        db.delete_job(job_id)
        return {"deleted": job_id}

    @app.post("/api/jobs/{job_id}/analyze")
    async def analyze(job_id: JobId):
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if job["source_kind"] == "url" and not job.get("local_path"):
            # Re-running a job from the history: the temporary video is gone,
            # so it has to be downloaded again.
            runner.submit_download(job_id, job["source"], None)
            return db.get_job(job_id)
        runner.submit_analyze(job_id)
        return db.get_job(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel(job_id: JobId):
        runner.request_cancel(job_id)
        return {"cancelling": job_id}

    @app.patch("/api/jobs/{job_id}/region")
    async def patch_region(job_id: JobId, patch: RegionPatchRequest):
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        overrides = job.get("overrides") or {}
        if patch.region is not None:
            overrides["region"] = patch.region.model_dump()
        if patch.songs is not None:
            overrides["songs"] = [s.model_dump() for s in patch.songs]
        db.update_job(job_id, overrides=overrides)
        return {"job_id": job_id, "overrides": overrides}

    @app.post("/api/jobs/{job_id}/render")
    async def render(job_id: JobId, req: RenderRequest):
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if job["status"] not in ("analyzed", "rendered", "failed", "cancelled"):
            raise HTTPException(409, f"the job is in state '{job['status']}'")

        prefs = config.load_preferences()
        output_dir = req.output_dir or prefs.get("output_dir")
        if not output_dir:
            raise HTTPException(400, "choose an output directory first")
        if req.output_dir and req.output_dir != prefs.get("output_dir"):
            config.save_preferences({"output_dir": req.output_dir})  # remember it

        overrides = job.get("overrides") or {}
        region = req.region.model_dump() if req.region else overrides.get("region")
        songs = ([s.model_dump() for s in req.songs] if req.songs
                 else overrides.get("songs"))
        runner.submit_render(job_id, region, songs, req.save_profile_name, output_dir)
        return db.get_job(job_id)

    @app.get("/api/jobs/{job_id}/frame")
    async def get_frame(job_id: JobId, index: int = 0):
        frames_dir = config.job_workdir(job_id) / "frames"
        paths = sorted(frames_dir.glob("frame_*.png")) if frames_dir.exists() else []
        if not paths:
            raise HTTPException(404, "no frames have been extracted for this job")
        index = max(0, min(index, len(paths) - 1))
        return FileResponse(paths[index], media_type="image/png")

    @app.get("/api/jobs/{job_id}/report")
    async def get_report(job_id: JobId):
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if job.get("render") is None:
            raise HTTPException(409, "this job has not been rendered yet")
        return job["render"]

    @app.websocket("/api/jobs/{job_id}/progress")
    async def progress_ws(websocket: WebSocket, job_id: JobId):
        """Job progress, until the job stops publishing or the client leaves.

        The disconnection only arrives through `receive()`, so the socket is
        watched alongside the queue. Waiting on the queue alone, this task
        survives the client: it ends when the next message fails to send, and
        for a job that never publishes again, never. Those tasks and their
        subscriptions pile up per progress screen, and uvicorn's graceful
        shutdown waits for them.
        """
        await websocket.accept()

        async def until_disconnected() -> None:
            while True:
                if (await websocket.receive())["type"] == "websocket.disconnect":
                    return

        with broker.subscribe(job_id) as queue:
            disconnected = asyncio.create_task(until_disconnected())
            try:
                while True:
                    message = asyncio.create_task(queue.get())
                    done, _pending = await asyncio.wait(
                        (message, disconnected), return_when=asyncio.FIRST_COMPLETED)
                    if disconnected in done:
                        message.cancel()
                        break
                    await websocket.send_text(json.dumps(message.result()))
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                disconnected.cancel()
                with contextlib.suppress(asyncio.CancelledError, RuntimeError, WebSocketDisconnect):
                    await disconnected

    # -------------------------------------------------------------- YouTube

    @app.post("/api/youtube/probe")
    async def youtube_probe(req: ProbeRequest):
        try:
            info = await asyncio.to_thread(ytdlp.probe, req.url)
        except ytdlp.YtdlpError as exc:
            raise HTTPException(400, {"message": str(exc), "kind": exc.kind,
                                      "hint": exc.hint}) from exc
        return asdict(info)

    @app.post("/api/youtube/jobs")
    async def youtube_job(req: UrlJobRequest):
        try:
            info = await asyncio.to_thread(ytdlp.probe, req.url)
            title = info.title
        except ytdlp.YtdlpError as exc:
            raise HTTPException(400, {"message": str(exc), "kind": exc.kind,
                                      "hint": exc.hint}) from exc
        job_id = db.new_job_id()
        job = db.create_job(job_id, source=info.url, source_kind="url",
                            title=title, status="downloading")
        runner.submit_download(job_id, info.url, req.format_id)
        return job

    @app.get("/api/ytdlp")
    async def ytdlp_version():
        return await asyncio.to_thread(ytdlp.version)

    @app.post("/api/ytdlp/update")
    async def ytdlp_update():
        try:
            return await asyncio.to_thread(ytdlp.update)
        except ytdlp.YtdlpError as exc:
            raise HTTPException(400, {"message": str(exc), "kind": exc.kind,
                                      "hint": exc.hint}) from exc

    # -------------------------------------------------------------- profiles

    @app.get("/api/profiles")
    async def get_profiles():
        return [asdict(p) for p in load_profiles(config.profiles_dir())]

    @app.post("/api/profiles/import")
    async def import_profiles(req: ProfileImportRequest):
        """Import profiles exported by another user, through an issue say.

        There is no cloud sync: the exchange is a JSON file.
        """
        existing = {p.name: p for p in load_profiles(config.profiles_dir())}
        imported = []
        for raw in req.profiles:
            try:
                profile = Profile(**ProfileIn.model_validate(raw).model_dump(mode="json"))
            except ValidationError as exc:
                problem = exc.errors()[0]
                where = ".".join(str(p) for p in problem["loc"])
                raise HTTPException(400, f"invalid profile: {where}: {problem['msg']}") from exc
            existing[profile.name] = profile
            imported.append(profile.name)
        path = config.profiles_dir() / "profiles.json"
        path.write_text(json.dumps([asdict(p) for p in existing.values()], indent=2))
        return {"imported": imported, "total": len(existing)}
