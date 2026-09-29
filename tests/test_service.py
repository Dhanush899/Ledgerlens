"""Replay keeps learning order even though retains run in the background."""
from __future__ import annotations

import asyncio

from app import agent, service
from app.config import ROOT
from app.memory import LocalBackend, MemoryService
from app.store import Store


class SlowBackend(LocalBackend):
    """Retain takes a while, like Hindsight's server-side extraction."""

    async def retain(self, *args, **kwargs):
        await asyncio.sleep(0.05)
        await super().retain(*args, **kwargs)


def test_replay_waits_for_vendor_memories(tmp_path, monkeypatch):
    seen: dict[str, int] = {}

    async def fake_suggest(invoice, vendor, flags, memories, memory_enabled=True):
        seen[invoice["id"]] = len(memories)
        return agent.Suggestion(action="escalate", confidence=0.5, reason="test",
                                recalled_count=len(memories), memory_enabled=memory_enabled)

    monkeypatch.setattr(service.agent, "suggest", fake_suggest)

    async def run():
        mem = MemoryService(SlowBackend(tmp_path / "mem.json"))
        await mem.setup()
        svc = service.LedgerLens(Store(ROOT / "data", tmp_path / "state.json"), mem)
        svc.start_replay(30)
        await svc._replay_task
        assert svc.replay_status["error"] is None
        assert len(svc.store.state["decisions"]) == len(svc.store.invoices)

        # every flagged invoice sees exactly the vendor's earlier flagged decisions
        prior: dict[str, int] = {}
        for inv in svc.store.invoices:
            if svc.store.flags_for(inv["id"]):
                assert seen[inv["id"]] == min(prior.get(inv["vendor_id"], 0), 10), inv["id"]
                prior[inv["vendor_id"]] = prior.get(inv["vendor_id"], 0) + 1
        assert mem.counts["retain"] == sum(prior.values())
    asyncio.run(run())
