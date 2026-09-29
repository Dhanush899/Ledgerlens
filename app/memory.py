"""Memory layer: a thin wrapper over Hindsight (with a local stand-in for offline dev).

One bank (``ledgerlens-ap``). Every clerk decision is retained as a natural-language
memory tagged ``vendor:<id>``, ``flag:<code>`` and ``decision:<action>``. Before each
suggestion we recall that vendor's history; vendor profiles come from reflect.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from .config import get_settings

log = logging.getLogger(__name__)

BANK_MISSION = (
    "You are the institutional memory of an Indian accounts-payable team. You remember how AP "
    "clerks resolved invoice exceptions (three-way match against PO and goods receipt) for each "
    "vendor: which recurring quirks are acceptable, the typical magnitudes that were approved "
    "(freight %, price variance %, GST rates, rounding amounts, partial receipts), and which "
    "invoices were held or escalated and why."
)

PROFILE_QUERY = (
    "Build an AP profile of vendor {name} ({vendor_id}). Cover: (1) recurring invoice quirks and "
    "the typical magnitudes the clerk accepted, (2) how each was resolved and why, (3) anything "
    "that was held or escalated, (4) concrete guidance for handling this vendor's next invoice. "
    "Be concise and use bullet points."
)


@dataclass
class MemoryItem:
    """A single recalled memory."""

    id: str
    text: str
    tags: list[str] = field(default_factory=list)
    timestamp: str | None = None
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MemoryBackend(Protocol):
    """What LedgerLens needs from a memory store."""

    name: str

    async def setup(self) -> None: ...
    async def retain(self, content: str, tags: list[str], metadata: dict[str, str],
                     timestamp: datetime, document_id: str) -> None: ...
    async def recall(self, query: str, tags: list[str], limit: int) -> list[MemoryItem]: ...
    async def reflect(self, query: str, tags: list[str]) -> tuple[str, list[MemoryItem]]: ...
    async def reset(self) -> None: ...


# ---------------------------------------------------------------------------
# Hindsight (Vectorize) backend
# ---------------------------------------------------------------------------
class HindsightBackend:
    """Hindsight Cloud / self-hosted via the official ``hindsight-client`` SDK."""

    name = "hindsight"

    def __init__(self, base_url: str, api_key: str | None, bank_id: str):
        from hindsight_client import Hindsight

        self.client = Hindsight(base_url=base_url, api_key=api_key, timeout=120)
        self.bank_id = bank_id

    async def setup(self) -> None:
        await self.client.acreate_bank(
            bank_id=self.bank_id, name="LedgerLens AP", mission=BANK_MISSION,
            retain_mission="Extract who (vendor), which exception, the magnitude, the clerk's "
                           "decision and the reason. Keep numbers exact.",
        )

    async def retain(self, content, tags, metadata, timestamp, document_id) -> None:
        await self.client.aretain(
            bank_id=self.bank_id, content=content, timestamp=timestamp, context="AP clerk decision",
            document_id=document_id, metadata=metadata, tags=tags,
        )

    async def recall(self, query, tags, limit) -> list[MemoryItem]:
        resp = await self.client.arecall(
            bank_id=self.bank_id, query=query, tags=tags, tags_match="any_strict",
            max_tokens=2048, budget="mid",
        )
        items = [MemoryItem(id=r.id, text=r.text, tags=r.tags or [],
                            timestamp=r.occurred_start or r.mentioned_at) for r in resp.results]
        return items[:limit]

    async def reflect(self, query, tags) -> tuple[str, list[MemoryItem]]:
        kwargs: dict[str, Any] = {"tags": tags, "tags_match": "any_strict"} if tags else {}
        resp = await self.client.areflect(
            bank_id=self.bank_id, query=query, budget="mid", include_facts=True, **kwargs,
        )
        facts = (resp.based_on.memories or []) if resp.based_on else []
        evidence = [MemoryItem(id=f.id or f"fact-{i}", text=f.text, timestamp=f.occurred_start)
                    for i, f in enumerate(facts)]
        return resp.text, evidence

    async def reset(self) -> None:
        try:
            await self.client.banks.delete_bank(self.bank_id)
        except Exception as e:  # bank may not exist yet
            log.info("delete_bank: %s", e)
        await self.setup()


# ---------------------------------------------------------------------------
# Local stand-in (JSON file + lexical scoring). Same interface, no network.
# ---------------------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9_%.]+")
_STOP = {"the", "a", "an", "of", "on", "and", "to", "for", "is", "in", "was", "with", "by", "as",
         "at", "it", "this", "that", "from", "inr", "invoice"}


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP]


class LocalBackend:
    """Offline memory used when HINDSIGHT_BASE_URL is not configured.

    Retain appends to a JSON file; recall is tag-filtered TF-IDF-style overlap with a
    recency tiebreak; reflect summarises the tagged memories with the Groq LLM.
    """

    name = "local"

    def __init__(self, path: Path):
        self.path = path
        self.items: list[dict[str, Any]] = []

    async def setup(self) -> None:
        if self.path.exists():
            self.items = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.items, indent=1, ensure_ascii=False), encoding="utf-8")

    async def retain(self, content, tags, metadata, timestamp, document_id) -> None:
        self.items = [m for m in self.items if m["document_id"] != document_id]
        self.items.append({"id": uuid.uuid4().hex[:12], "text": content, "tags": tags,
                           "metadata": metadata, "timestamp": timestamp.isoformat(),
                           "document_id": document_id})
        self._save()

    def _tagged(self, tags: list[str]) -> list[dict[str, Any]]:
        return [m for m in self.items if set(m["tags"]) & set(tags)] if tags else list(self.items)

    async def recall(self, query, tags, limit) -> list[MemoryItem]:
        pool = self._tagged(tags)
        if not pool:
            return []
        q = set(_tokens(query))
        df: dict[str, int] = {}
        for m in pool:
            for t in set(_tokens(m["text"]) + m["tags"]):
                df[t] = df.get(t, 0) + 1
        scored = []
        for m in pool:
            toks = set(_tokens(m["text"])) | {t.lower() for t in m["tags"]}
            score = sum(math.log(1 + len(pool) / df.get(t, 1)) for t in q & toks)
            scored.append((score, m["timestamp"], m))
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        return [MemoryItem(id=m["id"], text=m["text"], tags=m["tags"], timestamp=m["timestamp"],
                           score=round(s, 3)) for s, _, m in scored[:limit]]

    async def reflect(self, query, tags) -> tuple[str, list[MemoryItem]]:
        from . import llm

        pool = sorted(self._tagged(tags), key=lambda m: m["timestamp"])[-40:]
        if not pool:
            return "No memories yet.", []
        evidence = [MemoryItem(id=m["id"], text=m["text"], tags=m["tags"], timestamp=m["timestamp"])
                    for m in pool]
        facts = "\n".join(f"- {m['text']}" for m in pool)
        try:
            text = await llm.complete_text([
                {"role": "system", "content": BANK_MISSION + " Answer only from the memories given."},
                {"role": "user", "content": f"Memories:\n{facts}\n\n{query}"},
            ])
        except Exception as e:
            log.warning("local reflect LLM failed: %s", e)
            text = "LLM unavailable; raw memories:\n" + facts
        return text, evidence

    async def reset(self) -> None:
        self.items = []
        self._save()


# ---------------------------------------------------------------------------
# Public API used by the rest of the app
# ---------------------------------------------------------------------------
class MemoryService:
    """Owns the backend, the global MEMORY ON/OFF switch and a live log of memory operations."""

    def __init__(self, backend: MemoryBackend, bank_id: str = "", host: str | None = None):
        self.backend = backend
        self.enabled = True
        self.bank_id = bank_id
        self.host = host
        self.activity: deque[dict[str, Any]] = deque(maxlen=200)
        self.counts: dict[str, int] = {"retain": 0, "recall": 0, "reflect": 0}
        self._seq = 0

    async def setup(self) -> None:
        await self.backend.setup()

    @asynccontextmanager
    async def _track(self, op: str, summary: str, vendor_id: str | None = None):
        """Time one memory operation and add it to the activity feed (also on failure)."""
        started = time.perf_counter()
        entry: dict[str, Any] = {"op": op, "summary": summary, "vendor_id": vendor_id, "ok": True,
                                 "at": datetime.now().isoformat(timespec="seconds"), "result": None}
        try:
            yield entry
        except Exception as e:
            entry.update(ok=False, result=f"{type(e).__name__}: {e}"[:200])
            raise
        finally:
            self._seq += 1
            entry["id"] = self._seq
            entry["ms"] = int((time.perf_counter() - started) * 1000)
            if entry["ok"] and op in self.counts:
                self.counts[op] += 1
            self.activity.appendleft(entry)

    def info(self) -> dict[str, Any]:
        """Backend identity and counters for the memory console."""
        return {"backend": self.backend.name, "bank_id": self.bank_id, "host": self.host,
                "enabled": self.enabled, "counts": dict(self.counts)}

    async def retain_decision(
        self, invoice: dict[str, Any], vendor: dict[str, Any], flags: list[dict[str, Any]],
        action: str, clerk_note: str, decided_at: datetime | None = None,
    ) -> str:
        """Store a clerk decision as a memory. Always runs, even when recall is off."""
        text = format_decision_memory(invoice, vendor, flags, action, clerk_note)
        when = decided_at or datetime.fromisoformat(invoice["date"])
        tags = [f"vendor:{vendor['id']}", f"decision:{action}"] + sorted({f"flag:{f['code']}" for f in flags})
        async with self._track("retain", f"{action} {invoice['invoice_number']} ({vendor['name']})",
                               vendor["id"]) as entry:
            await self.backend.retain(
                content=text, tags=tags, timestamp=when, document_id=f"decision-{invoice['id']}",
                metadata={"invoice_id": invoice["id"], "vendor_id": vendor["id"], "decision": action},
            )
            entry["result"] = text
        return text

    async def recall_vendor_history(
        self, vendor: dict[str, Any], flags: list[dict[str, Any]], limit: int = 10, force: bool = False
    ) -> list[MemoryItem]:
        """Recall past decisions for this vendor relevant to these exceptions.

        Returns [] when memory is switched off (the before/after demo toggle) unless ``force``.
        """
        if not self.enabled and not force:
            return []
        query = (f"How did the AP clerk handle {vendor['name']} ({vendor['id']}) invoices with "
                 + "; ".join(f"{f['code']}: {f['message']}" for f in flags) + "?")
        codes = ", ".join(sorted({f["code"] for f in flags}))
        async with self._track("recall", f"{vendor['name']}: {codes}", vendor["id"]) as entry:
            items = await self.backend.recall(query, tags=[f"vendor:{vendor['id']}"], limit=limit)
            entry["result"] = f"{len(items)} memories"
        return items

    async def build_vendor_profile(self, vendor: dict[str, Any]) -> tuple[str, list[MemoryItem]]:
        """Synthesise a vendor profile from all its memories via reflect. Returns (text, evidence)."""
        async with self._track("reflect", f"profile of {vendor['name']}", vendor["id"]) as entry:
            text, evidence = await self.backend.reflect(
                PROFILE_QUERY.format(name=vendor["name"], vendor_id=vendor["id"]),
                tags=[f"vendor:{vendor['id']}"],
            )
            entry["result"] = f"based on {len(evidence)} memories"
        return text, evidence

    async def ask(self, question: str, vendor: dict[str, Any] | None = None) -> tuple[str, list[MemoryItem]]:
        """Free-form question over the whole bank (or one vendor) via reflect."""
        scope = vendor["name"] if vendor else "all vendors"
        async with self._track("reflect", f'ask ({scope}): "{question[:80]}"',
                               vendor["id"] if vendor else None) as entry:
            text, evidence = await self.backend.reflect(
                question, tags=[f"vendor:{vendor['id']}"] if vendor else [])
            entry["result"] = f"based on {len(evidence)} memories"
        return text, evidence

    async def list_vendor_memories(self, vendor: dict[str, Any], limit: int = 30) -> list[MemoryItem]:
        """Everything remembered about a vendor (ignores the toggle; used by the profile page)."""
        async with self._track("recall", f"browse {vendor['name']}", vendor["id"]) as entry:
            items = await self.backend.recall(
                f"All AP decisions for {vendor['name']} ({vendor['id']})",
                tags=[f"vendor:{vendor['id']}"], limit=limit)
            entry["result"] = f"{len(items)} memories"
        return items

    async def reset(self) -> None:
        """Wipe the bank."""
        async with self._track("reset", f"wipe bank {self.bank_id}"):
            await self.backend.reset()


def format_decision_memory(
    invoice: dict[str, Any], vendor: dict[str, Any], flags: list[dict[str, Any]],
    action: str, clerk_note: str,
) -> str:
    """Render a decision as a self-contained natural-language memory (numbers kept exact)."""
    verb = {"approve": "APPROVED", "hold": "put ON HOLD", "escalate": "ESCALATED"}[action]
    exc = "; ".join(f"{f['code']} - {f['message']}" for f in flags) or "no exceptions"
    return (f"On {invoice['date']} the AP clerk {verb} invoice {invoice['invoice_number']} "
            f"(INR {invoice['total']:,.2f}) from vendor {vendor['name']} ({vendor['id']}). "
            f"Exceptions: {exc}. Clerk note: {clerk_note.strip() or 'none'}")


def create_memory_service() -> MemoryService:
    """Hindsight when HINDSIGHT_BASE_URL is set, otherwise the local stand-in."""
    s = get_settings()
    if s.hindsight_base_url:
        backend: MemoryBackend = HindsightBackend(s.hindsight_base_url, s.hindsight_api_key, s.bank_id)
    else:
        log.warning("HINDSIGHT_BASE_URL not set: using local memory stand-in")
        backend = LocalBackend(s.var_dir / "local_memory.json")
    host = urlparse(s.hindsight_base_url).netloc if s.hindsight_base_url else None
    return MemoryService(backend, bank_id=s.bank_id, host=host)
