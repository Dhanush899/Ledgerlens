"""Orchestration: rules -> recall -> agent -> clerk decision -> retain. Plus replay and metrics."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from . import agent
from .memory import MemoryService
from .store import Store

log = logging.getLogger(__name__)

WEEKS = [(1, 7, "Week 1 (1-7 Sep)"), (8, 14, "Week 2 (8-14 Sep)"),
         (15, 21, "Week 3 (15-21 Sep)"), (22, 30, "Week 4 (22-30 Sep)")]


class LedgerLens:
    """The AP exception workflow over a Store and a MemoryService."""

    def __init__(self, store: Store, memory: MemoryService):
        self.store = store
        self.memory = memory
        self.replay_status: dict[str, Any] = {"running": False, "done": 0, "total": 0,
                                              "current": None, "error": None, "through_day": None}
        self._replay_task: asyncio.Task | None = None

    # ---- queue ---------------------------------------------------------------
    def queue(self) -> list[dict[str, Any]]:
        """Summary row per invoice for the queue view."""
        rows = []
        for inv in self.store.invoices:
            flags = self.store.flags_for(inv["id"])
            sug = self.store.state["suggestions"].get(inv["id"])
            dec = self.store.state["decisions"].get(inv["id"])
            rows.append({
                "id": inv["id"], "invoice_number": inv["invoice_number"], "day": inv["day"],
                "date": inv["date"], "vendor_id": inv["vendor_id"],
                "vendor_name": self.store.vendors[inv["vendor_id"]]["name"], "total": inv["total"],
                "flags": [f["code"] for f in flags], "max_severity": _max_severity(flags),
                "suggestion": {k: sug[k] for k in ("action", "confidence", "needs_human")} if sug else None,
                "decision": {k: dec[k] for k in ("action", "decided_by")} if dec else None,
            })
        return rows

    # ---- suggest / decide ------------------------------------------------------
    async def suggest(self, invoice_id: str) -> dict[str, Any]:
        """Recall vendor memories and ask the agent. Clean invoices go straight through."""
        ctx = self.store.context(invoice_id)
        if not ctx["flags"]:
            s = agent.Suggestion(action="approve", confidence=1.0, guardrail="straight-through",
                                 reason="Clean three-way match: PO, goods receipt and invoice agree.",
                                 memory_enabled=self.memory.enabled).to_dict()
            s["recalled"] = []
        else:
            memories = await self.memory.recall_vendor_history(ctx["vendor"], ctx["flags"])
            sug = await agent.suggest(ctx["invoice"], ctx["vendor"], ctx["flags"], memories,
                                      memory_enabled=self.memory.enabled)
            s = sug.to_dict()
            s["recalled"] = [m.to_dict() for m in memories]
        s["created_at"] = datetime.now().isoformat(timespec="seconds")
        self.store.record_suggestion(invoice_id, s)
        return s

    async def decide(self, invoice_id: str, action: str, note: str, decided_by: str = "clerk") -> dict[str, Any]:
        """Record the clerk's decision and retain it in memory (exceptions only)."""
        if action not in agent.ACTIONS:
            raise ValueError(f"action must be one of {agent.ACTIONS}")
        ctx = self.store.context(invoice_id)
        sug = ctx["suggestion"]
        memory_text = None
        if ctx["flags"]:
            memory_text = await self.memory.retain_decision(
                ctx["invoice"], ctx["vendor"], ctx["flags"], action, note)
        decision = {
            "action": action, "note": note, "decided_by": decided_by,
            "decided_at": datetime.now().isoformat(timespec="seconds"),
            "had_exceptions": bool(ctx["flags"]),
            "suggested_action": sug["action"] if sug else None,
            "suggested_confidence": sug["confidence"] if sug else None,
            "needs_human": sug["needs_human"] if sug else True,
            "memory_enabled": sug["memory_enabled"] if sug else self.memory.enabled,
            "agreed": bool(sug and sug["action"] == action),
            "retained_memory": memory_text,
        }
        self.store.record_decision(invoice_id, decision)
        return decision

    # ---- seed + replay -----------------------------------------------------------
    async def seed_history(self) -> int:
        """Replay August's historical clerk decisions into memory."""
        for h in self.store.history:
            vendor = self.store.vendors[h["vendor_id"]]
            pseudo_invoice = {"id": h["id"], "invoice_number": h["invoice_number"], "date": h["date"],
                              "total": h["total"]}
            await self.memory.retain_decision(pseudo_invoice, vendor, h["flags"], h["decision"], h["note"])
        return len(self.store.history)

    def start_replay(self, through_day: int) -> dict[str, Any]:
        """Kick off a background replay of undecided invoices up to ``through_day``."""
        if self.replay_status["running"]:
            return self.replay_status
        todo = [i for i in self.store.invoices
                if i["day"] <= through_day and i["id"] not in self.store.state["decisions"]]
        self.replay_status = {"running": True, "done": 0, "total": len(todo), "current": None,
                              "error": None, "through_day": through_day}
        self._replay_task = asyncio.create_task(self._replay(todo))
        return self.replay_status

    async def _replay(self, todo: list[dict]) -> None:
        try:
            for inv in todo:
                self.replay_status["current"] = inv["id"]
                await self.suggest(inv["id"])
                truth = self.store.ground_truth[inv["id"]]
                has_flags = bool(self.store.flags_for(inv["id"]))
                await self.decide(inv["id"], truth["expected_action"], truth["clerk_note"],
                                  decided_by="replay-clerk" if has_flags else "straight-through")
                self.replay_status["done"] += 1
        except Exception as e:  # surface to UI instead of dying silently
            log.exception("replay failed")
            self.replay_status["error"] = f"{type(e).__name__}: {e}"
        finally:
            self.replay_status["running"] = False
            self.replay_status["current"] = None

    # ---- metrics -------------------------------------------------------------------
    def metrics(self) -> dict[str, Any]:
        """Learning curve: share of exceptions needing a human, per week of September."""
        decisions = self.store.state["decisions"]
        weeks = []
        for lo, hi, label in WEEKS:
            rows = [(inv, decisions[inv["id"]]) for inv in self.store.invoices
                    if lo <= inv["day"] <= hi and inv["id"] in decisions]
            exc = [d for _, d in rows if d["had_exceptions"]]
            human = sum(1 for d in exc if d["needs_human"])
            agreed = sum(1 for d in exc if d["agreed"])
            weeks.append({
                "label": label, "processed": len(rows), "clean": len(rows) - len(exc),
                "exceptions": len(exc), "human_needed": human, "auto_handled": len(exc) - human,
                "human_rate": round(human / len(exc), 3) if exc else None,
                "agreement": round(agreed / len(exc), 3) if exc else None,
            })
        all_exc = [d for d in decisions.values() if d["had_exceptions"]]
        return {
            "weeks": weeks,
            "totals": {
                "invoices": len(self.store.invoices), "processed": len(decisions),
                "exceptions": len(all_exc),
                "human_needed": sum(1 for d in all_exc if d["needs_human"]),
                "agreement": round(sum(d["agreed"] for d in all_exc) / len(all_exc), 3) if all_exc else None,
            },
        }


def _max_severity(flags: list[dict]) -> str | None:
    order = {"low": 1, "medium": 2, "high": 3}
    return max((f["severity"] for f in flags), key=order.get, default=None)
