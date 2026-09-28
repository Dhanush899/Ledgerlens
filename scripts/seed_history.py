"""Replay August's historical clerk decisions into memory (Hindsight or the local stand-in).

Run:  python scripts/seed_history.py [--reset]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.memory import create_memory_service  # noqa: E402
from app.service import LedgerLens  # noqa: E402
from app.store import Store  # noqa: E402


async def main(reset: bool) -> None:
    s = get_settings()
    memory = create_memory_service()
    await memory.setup()
    if reset:
        await memory.reset()
    svc = LedgerLens(Store(s.data_dir, s.var_dir / "state.json"), memory)
    n = await svc.seed_history()
    print(f"Retained {n} historical decisions into '{s.bank_id}' ({memory.backend.name} backend).")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true", help="wipe the memory bank first")
    asyncio.run(main(p.parse_args().reset))
