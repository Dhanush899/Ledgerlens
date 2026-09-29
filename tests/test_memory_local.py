"""Tests for the local memory stand-in and MemoryService wiring."""
from __future__ import annotations

import asyncio

from app.memory import LocalBackend, MemoryService

VENDOR = {"id": "V01", "name": "Deccan Steel Traders"}
OTHER = {"id": "V02", "name": "Other"}
FREIGHT = [{"code": "UNEXPECTED_LINE", "severity": "medium",
            "message": "Line 'Freight' (INR 900, 1.5% of goods value) is not on the PO.", "details": {}}]
ROUND = [{"code": "TOTAL_MISMATCH", "severity": "low", "message": "Stated total differs by INR +0.40.",
          "details": {}}]


def _inv(i, date="2026-09-01"):
    return {"id": f"INV-{i}", "invoice_number": f"DST/{i}", "date": date, "total": 1000.0}


def test_retain_recall_is_vendor_scoped_and_relevant(tmp_path):
    async def run():
        m = MemoryService(LocalBackend(tmp_path / "mem.json"))
        await m.setup()
        await m.retain_decision(_inv(1), VENDOR, ROUND, "approve", "rounding ok")
        await m.retain_decision(_inv(2), VENDOR, FREIGHT, "approve", "freight under 2% ok")
        await m.retain_decision(_inv(3), OTHER, FREIGHT, "hold", "freight too high")
        got = await m.recall_vendor_history(VENDOR, FREIGHT)
        assert len(got) == 2
        assert "freight under 2%" in got[0].text          # most relevant first
        assert all("V01" in t for x in got for t in x.tags if t.startswith("vendor:"))
        m.enabled = False
        assert await m.recall_vendor_history(VENDOR, FREIGHT) == []
    asyncio.run(run())


def test_redeciding_replaces_memory_and_persists(tmp_path):
    async def run():
        path = tmp_path / "mem.json"
        m = MemoryService(LocalBackend(path))
        await m.setup()
        await m.retain_decision(_inv(1), VENDOR, FREIGHT, "escalate", "not sure")
        await m.retain_decision(_inv(1), VENDOR, FREIGHT, "approve", "checked contract")
        reloaded = LocalBackend(path)
        await reloaded.setup()
        assert len(reloaded.items) == 1 and "APPROVED" in reloaded.items[0]["text"]
        await m.reset()
        assert await m.recall_vendor_history(VENDOR, FREIGHT) == []
    asyncio.run(run())


def test_activity_log_and_counts(tmp_path):
    async def run():
        m = MemoryService(LocalBackend(tmp_path / "mem.json"), bank_id="b")
        await m.setup()
        await m.retain_decision(_inv(1), VENDOR, FREIGHT, "approve", "ok")
        await m.recall_vendor_history(VENDOR, FREIGHT)
        m.enabled = False
        assert await m.recall_vendor_history(VENDOR, FREIGHT) == []           # toggle: no call made
        assert len(await m.recall_vendor_history(VENDOR, FREIGHT, force=True)) == 1
        assert m.counts == {"retain": 1, "recall": 2, "reflect": 0}
        ops = [a["op"] for a in m.activity]
        assert ops == ["recall", "recall", "retain"]                           # newest first
        assert m.activity[-1]["vendor_id"] == "V01" and "APPROVED" in m.activity[-1]["result"]
        assert m.info()["counts"]["retain"] == 1
    asyncio.run(run())


def test_ask_scopes_to_vendor_and_returns_evidence(tmp_path, monkeypatch):
    from app import llm

    async def fake_text(messages, max_tokens=900):
        return "answer"

    monkeypatch.setattr(llm, "complete_text", fake_text)

    async def run():
        m = MemoryService(LocalBackend(tmp_path / "mem.json"))
        await m.setup()
        await m.retain_decision(_inv(1), VENDOR, FREIGHT, "approve", "ok")
        await m.retain_decision(_inv(2), OTHER, FREIGHT, "hold", "no")
        text, ev = await m.ask("Who bills freight?")
        assert text == "answer" and len(ev) == 2
        _, ev = await m.ask("Freight?", VENDOR)
        assert len(ev) == 1 and "V01" in ev[0].text
        assert m.counts["reflect"] == 2
    asyncio.run(run())
