"""LLM agent: exception + recalled memories -> {action, confidence, reason, cited_memories}.

The LLM proposes; deterministic guardrails dispose:
  * a suspected duplicate is never approved,
  * nothing is approved without citing a real precedent from memory,
  * any failure (API, JSON, validation) falls back to ``escalate``.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from . import llm
from .memory import MemoryItem
from .rules import DUPLICATE

log = logging.getLogger(__name__)

ACTIONS = ("approve", "hold", "escalate")
HUMAN_REVIEW_CONFIDENCE = 0.7

SYSTEM_PROMPT = """You are LedgerLens, an accounts-payable exception agent for an Indian manufacturer.
A deterministic three-way match (invoice vs PO vs goods receipt) has flagged exceptions on an invoice.
You also get memories of how human AP clerks handled this vendor before. Recommend ONE action:

- "approve": ONLY if the memories show the clerk approved the SAME kind of exception for THIS vendor,
  and the current magnitude (freight %, price variance %, GST rates, rounding amount, received %) is
  within or very close to what was approved before. You MUST cite those memories.
- "hold": pay nothing yet. Use when the invoice looks like a duplicate, when the magnitude clearly
  exceeds the vendor's learned pattern (e.g. freight 9% when history shows ~1.5%), or when past
  decisions on this pattern were holds.
- "escalate": send to a senior reviewer. Use when there is no relevant precedent, precedents conflict,
  or you are not sure. With no memories you should escalate.

Every flagged exception must be covered by precedent to approve. Confidence (0 to 1) reflects the
strength of precedent: one matching memory ~0.7, two or more consistent ones 0.85-0.95.
Reply with ONLY a JSON object:
{"action": "approve|hold|escalate", "confidence": 0.0, "reason": "<=2 sentences, mention numbers",
 "cited_memories": ["M1", ...]}"""


@dataclass
class Suggestion:
    """The agent's recommendation for one invoice."""

    action: str
    confidence: float
    reason: str
    cited_memories: list[dict[str, Any]] = field(default_factory=list)
    recalled_count: int = 0
    memory_enabled: bool = True
    model: str | None = None
    guardrail: str | None = None
    latency_ms: int = 0

    @property
    def needs_human(self) -> bool:
        """True when a person has to look at it (escalated or low confidence)."""
        return self.action == "escalate" or self.confidence < HUMAN_REVIEW_CONFIDENCE

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["needs_human"] = self.needs_human
        return d


def build_user_message(
    invoice: dict[str, Any], vendor: dict[str, Any], flags: list[dict[str, Any]],
    memories: list[MemoryItem],
) -> str:
    """Compact, model-friendly description of the case."""
    lines = [
        f"Vendor: {vendor['name']} ({vendor['id']}), GSTIN {vendor['gstin']}, terms {vendor['payment_terms']}",
        f"Invoice {invoice['invoice_number']} dated {invoice['date']}, PO {invoice.get('po_number') or 'NONE'}, "
        f"subtotal INR {invoice['subtotal']:,.2f}, tax INR {invoice['tax']:,.2f}, total INR {invoice['total']:,.2f}",
        "",
        "Flagged exceptions:",
    ]
    for f in flags:
        lines.append(f"- {f['code']} ({f['severity']}): {f['message']} details={json.dumps(f['details'])}")
    lines += ["", "Memories of past clerk decisions for this vendor:"]
    if memories:
        lines += [f"[M{i}] {m.text}" for i, m in enumerate(memories, 1)]
    else:
        lines.append("(none)")
    return "\n".join(lines)


def make_validator(memories: list[MemoryItem]):
    """Validate/normalise the model's JSON; map M-labels back to memory objects."""
    by_label = {f"M{i}": m for i, m in enumerate(memories, 1)}
    by_id = {m.id: m for m in memories}

    def validate(obj: dict[str, Any]) -> dict[str, Any]:
        action = str(obj.get("action", "")).strip().lower()
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}, got {action!r}")
        try:
            confidence = float(obj.get("confidence", 0))
        except (TypeError, ValueError):
            raise ValueError("confidence must be a number")
        if confidence > 1:  # model answered in percent
            confidence /= 100
        reason = str(obj.get("reason", "")).strip()
        if not reason:
            raise ValueError("reason is required")
        cited = obj.get("cited_memories") or []
        if isinstance(cited, str):
            cited = [cited]
        resolved: list[MemoryItem] = []
        for c in cited:
            key = str(c).strip().strip("[]").upper()
            m = by_label.get(key) or by_id.get(str(c))
            if m and m not in resolved:
                resolved.append(m)
        return {"action": action, "confidence": max(0.0, min(1.0, confidence)),
                "reason": reason, "cited": resolved}

    return validate


def apply_guardrails(
    result: dict[str, Any], flags: list[dict[str, Any]]
) -> tuple[dict[str, Any], str | None]:
    """Deterministic safety net over the LLM output. Returns (result, guardrail_note)."""
    codes = {f["code"] for f in flags}
    if DUPLICATE in codes and result["action"] == "approve":
        return {**result, "action": "hold", "confidence": max(result["confidence"], 0.9),
                "reason": "Suspected duplicate invoice: never auto-approved. " + result["reason"]}, \
            "duplicate-never-approved"
    if result["action"] == "approve" and not result["cited"]:
        return {**result, "action": "escalate", "confidence": min(result["confidence"], 0.5),
                "reason": "No precedent in memory for this exception, so a human must decide. "
                          + result["reason"]}, "approve-requires-precedent"
    return result, None


def fallback(reason: str, memories: list[MemoryItem], memory_enabled: bool) -> Suggestion:
    """Safe default when the LLM cannot be used."""
    return Suggestion(action="escalate", confidence=0.0, reason=reason, recalled_count=len(memories),
                      memory_enabled=memory_enabled, guardrail="safe-fallback")


async def suggest(
    invoice: dict[str, Any], vendor: dict[str, Any], flags: list[dict[str, Any]],
    memories: list[MemoryItem], memory_enabled: bool = True,
) -> Suggestion:
    """Recommend approve / hold / escalate for a flagged invoice."""
    started = time.perf_counter()
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(invoice, vendor, flags, memories)}]
    try:
        raw, model = await llm.complete_json(messages, make_validator(memories))
    except Exception as e:
        log.warning("agent fell back to escalate: %s", e)
        s = fallback(f"Agent unavailable ({type(e).__name__}); escalating for human review.",
                     memories, memory_enabled)
        s.latency_ms = int((time.perf_counter() - started) * 1000)
        return s

    result, guardrail = apply_guardrails(raw, flags)
    return Suggestion(
        action=result["action"], confidence=round(result["confidence"], 2), reason=result["reason"],
        cited_memories=[m.to_dict() for m in result["cited"]], recalled_count=len(memories),
        memory_enabled=memory_enabled, model=model, guardrail=guardrail,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
