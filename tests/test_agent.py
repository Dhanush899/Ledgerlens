"""Tests for agent parsing, guardrails and the safe fallback (no network)."""
from __future__ import annotations

import asyncio

import pytest

from app import agent, llm
from app.memory import MemoryItem

MEMS = [MemoryItem(id="abc", text="Approved freight 1.4%"), MemoryItem(id="def", text="Approved freight 1.7%")]
FREIGHT = [{"code": "UNEXPECTED_LINE", "severity": "medium", "message": "Freight", "details": {}}]
DUP = [{"code": "DUPLICATE", "severity": "high", "message": "dup", "details": {}}]


def test_extract_json_handles_think_and_fences():
    raw = '<think>hmm {"no": 1}</think>Sure!\n```json\n{"action": "hold", "confidence": 0.8}\n```'
    assert llm.extract_json(raw) == {"action": "hold", "confidence": 0.8}


def test_extract_json_rejects_garbage():
    with pytest.raises(ValueError):
        llm.extract_json("I think you should approve it.")


def test_validator_maps_labels_and_normalises():
    v = agent.make_validator(MEMS)
    out = v({"action": "Approve", "confidence": 90, "reason": "ok", "cited_memories": ["M2", "[M1]", "M9"]})
    assert out["action"] == "approve"
    assert out["confidence"] == 0.9
    assert [m.id for m in out["cited"]] == ["def", "abc"]


@pytest.mark.parametrize("bad", [
    {"action": "pay", "confidence": 0.5, "reason": "x"},
    {"action": "hold", "confidence": "high", "reason": "x"},
    {"action": "hold", "confidence": 0.5, "reason": ""},
])
def test_validator_rejects_bad_output(bad):
    with pytest.raises(ValueError):
        agent.make_validator(MEMS)(bad)


def test_guardrail_duplicate_never_approved():
    res, g = agent.apply_guardrails({"action": "approve", "confidence": 0.9, "reason": "r", "cited": MEMS}, DUP)
    assert res["action"] == "hold" and g == "duplicate-never-approved"


def test_guardrail_approve_requires_precedent():
    res, g = agent.apply_guardrails({"action": "approve", "confidence": 0.9, "reason": "r", "cited": []}, FREIGHT)
    assert res["action"] == "escalate" and res["confidence"] <= 0.5 and g == "approve-requires-precedent"


def test_guardrail_passes_supported_approve():
    res, g = agent.apply_guardrails({"action": "approve", "confidence": 0.9, "reason": "r", "cited": MEMS}, FREIGHT)
    assert res["action"] == "approve" and g is None


def test_suggest_falls_back_to_escalate_when_llm_fails(monkeypatch):
    async def boom(*a, **k):
        raise llm.LLMUnavailable("down")

    monkeypatch.setattr(llm, "complete_json", boom)
    inv = {"invoice_number": "X", "date": "2026-09-01", "subtotal": 1, "tax": 0, "total": 1}
    vendor = {"id": "V01", "name": "V", "gstin": "G", "payment_terms": "Net 30"}
    s = asyncio.run(agent.suggest(inv, vendor, FREIGHT, MEMS))
    assert s.action == "escalate" and s.guardrail == "safe-fallback" and s.needs_human
