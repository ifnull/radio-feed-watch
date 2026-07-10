"""FastAPI app: dashboard UI + SSE + clip APIs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from radio_feed_watch.bus import EventBus
from radio_feed_watch.config import AppConfig
from radio_feed_watch.storage.clips import ClipStore

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(app_config: AppConfig, bus: EventBus, store: ClipStore) -> FastAPI:
    api = FastAPI(title="radio-feed-watch", version="0.1.0")
    is_demo = app_config.dashboard.mode == "demo"
    center = app_config.locale.dashboard.map_center or {"lat": 0.0, "lon": 0.0, "zoom": 10}

    @api.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "mode": app_config.dashboard.mode, "locale": app_config.locale.id}

    @api.get("/api/meta")
    async def meta() -> dict:
        return {
            "brand_name": app_config.dashboard.brand_name,
            "mode": app_config.dashboard.mode,
            "locale": {
                "id": app_config.locale.id,
                "label": app_config.locale.label,
            },
            "map_center": center,
            "demo_title": app_config.locale.dashboard.demo_title,
            "demo_blurb": app_config.locale.dashboard.demo_blurb,
            "sources": [
                {
                    "id": s.id,
                    "label": s.label,
                    "type": s.type,
                    "enabled": s.enabled,
                    "mode": getattr(s, "mode", None),
                    "feed_id": s.feed_id,
                }
                for s in app_config.locale.sources
            ],
            "waypoints": []
            if is_demo
            else [w.model_dump() for w in app_config.waypoints],
            "ops": not is_demo,
            "transcript_burst_gap_s": app_config.dashboard.transcript_burst_gap_s,
        }

    @api.get("/api/snapshot")
    async def snapshot() -> dict:
        data = bus.snapshot()
        if is_demo:
            data = {**data, "alerts": []}
        return data

    @api.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        queue = bus.subscribe()

        async def gen():
            try:
                snap = bus.snapshot()
                yield f"data: {json.dumps({'kind': 'snapshot', **snap})}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                        if is_demo and event.get("kind") == "alert":
                            continue
                        yield f"data: {json.dumps(event, default=str)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                bus.unsubscribe(queue)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @api.get("/api/clips/{clip_id}")
    async def get_clip(clip_id: str) -> FileResponse:
        record = store.get(clip_id)
        if not record:
            raise HTTPException(404, "clip not found")
        path = Path(record.path)
        if not path.exists():
            raise HTTPException(404, "clip file missing")
        media = "audio/wav" if path.suffix == ".wav" else "audio/mpeg"
        return FileResponse(path, media_type=media, filename=path.name)

    if not is_demo:

        @api.post("/api/clips/{clip_id}/save")
        async def save_clip(clip_id: str) -> dict:
            record = store.get(clip_id)
            if not record:
                raise HTTPException(404, "clip not found")
            store.set_saved(clip_id, True)
            return {"clip_id": clip_id, "saved": True}

        @api.delete("/api/clips/{clip_id}/save")
        async def unsave_clip(clip_id: str) -> dict:
            record = store.get(clip_id)
            if not record:
                raise HTTPException(404, "clip not found")
            store.set_saved(clip_id, False)
            return {"clip_id": clip_id, "saved": False}

    if WEB_DIR.exists():
        api.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @api.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        index_path = WEB_DIR / "index.html"
        if not index_path.exists():
            return HTMLResponse("<h1>radio-feed-watch</h1><p>Dashboard assets missing.</p>")
        return HTMLResponse(index_path.read_text(encoding="utf-8"))

    return api
