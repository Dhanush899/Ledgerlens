"""FastAPI app: invoice queue, suggestions, clerk decisions, vendor profiles, memory controls.

Run:  uvicorn app.api:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ROOT, get_settings
from .memory import create_memory_service
from .service import LedgerLens
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

svc: LedgerLens | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global svc
    s = get_settings()
    memory = create_memory_service()
    await memory.setup()
    svc = LedgerLens(Store(s.data_dir, s.var_dir / "state.json"), memory)
    yield


app = FastAPI(title="LedgerLens", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def service() -> LedgerLens:
    assert svc is not None, "app not started"
    return svc


def _invoice_or_404(invoice_id: str) -> None:
    if invoice_id not in service().store.by_id:
        raise HTTPException(404, f"unknown invoice {invoice_id}")


def _vendor_or_404(vendor_id: str) -> dict:
    v = service().store.vendors.get(vendor_id)
    if not v:
        raise HTTPException(404, f"unknown vendor {vendor_id}")
    return v


class DecisionIn(BaseModel):
    action: Literal["approve", "hold", "escalate"]
    note: str = Field("", max_length=2000)


class ToggleIn(BaseModel):
    enabled: bool


class ReplayIn(BaseModel):
    through_day: int = Field(30, ge=1, le=30)


class ResetIn(BaseModel):
    memory: bool = True
    queue: bool = True


@app.get("/api/health")
async def health() -> dict:
    s = get_settings()
    return {"memory_backend": service().memory.backend.name, "memory_enabled": service().memory.enabled,
            "bank_id": s.bank_id, "llm_configured": bool(s.groq_api_key),
            "models": [s.groq_model, s.groq_fallback_model]}


@app.get("/api/invoices")
async def list_invoices() -> list[dict]:
    return service().queue()


@app.get("/api/invoices/{invoice_id}")
async def get_invoice(invoice_id: str) -> dict:
    _invoice_or_404(invoice_id)
    return service().store.context(invoice_id)


@app.post("/api/invoices/{invoice_id}/suggest")
async def suggest(invoice_id: str) -> dict:
    _invoice_or_404(invoice_id)
    return await service().suggest(invoice_id)


@app.post("/api/invoices/{invoice_id}/decision")
async def decide(invoice_id: str, body: DecisionIn) -> dict:
    _invoice_or_404(invoice_id)
    return await service().decide(invoice_id, body.action, body.note)


@app.get("/api/vendors")
async def vendors() -> list[dict]:
    st = service().store
    counts: dict[str, dict] = {}
    for inv in st.invoices:
        c = counts.setdefault(inv["vendor_id"], {"invoices": 0, "decided": 0})
        c["invoices"] += 1
        c["decided"] += inv["id"] in st.state["decisions"]
    return [{**v, **counts.get(v["id"], {})} for v in st.vendors.values()]


@app.get("/api/vendors/{vendor_id}/memories")
async def vendor_memories(vendor_id: str) -> list[dict]:
    v = _vendor_or_404(vendor_id)
    return [m.to_dict() for m in await service().memory.list_vendor_memories(v)]


@app.get("/api/vendors/{vendor_id}/profile")
async def vendor_profile(vendor_id: str) -> dict:
    v = _vendor_or_404(vendor_id)
    return {"vendor": v, "profile": await service().memory.build_vendor_profile(v),
            "backend": service().memory.backend.name}


@app.get("/api/memory")
async def memory_state() -> dict:
    return {"enabled": service().memory.enabled, "backend": service().memory.backend.name}


@app.post("/api/memory/toggle")
async def memory_toggle(body: ToggleIn) -> dict:
    service().memory.enabled = body.enabled
    return await memory_state()


@app.post("/api/memory/seed")
async def memory_seed() -> dict:
    return {"retained": await service().seed_history()}


@app.post("/api/reset")
async def reset(body: ResetIn) -> dict:
    if service().replay_status["running"]:
        raise HTTPException(409, "replay in progress")
    if body.memory:
        await service().memory.reset()
    if body.queue:
        service().store.reset()
    return {"ok": True}


@app.post("/api/replay")
async def replay(body: ReplayIn) -> dict:
    return service().start_replay(body.through_day)


@app.get("/api/replay")
async def replay_status() -> dict:
    return service().replay_status


@app.get("/api/metrics")
async def metrics() -> dict:
    return service().metrics()


# Serve the built frontend (npm run build) from the same process for demos.
_dist = ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        return FileResponse(_dist / "index.html")
