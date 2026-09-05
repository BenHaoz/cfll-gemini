"""已见条目状态（用于判定"本周新增"）。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .models import Item


class State:
    def __init__(self, path: Path | None = None):
        self.path = path or DATA_DIR / "state.json"
        self.data: dict[str, Any] = {"seen": {}, "runs": []}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        self.data.setdefault("seen", {})
        self.data.setdefault("runs", [])

    def is_new(self, item: Item) -> bool:
        return item.key() not in self.data["seen"]

    def mark(self, items: list[Item], today: date | None = None) -> None:
        d = (today or date.today()).isoformat()
        for it in items:
            self.data["seen"].setdefault(it.key(), {"first_seen": d, "title": it.title[:120], "kind": it.kind})

    def record_run(self, summary: dict[str, Any]) -> None:
        self.data["runs"].append(summary)
        self.data["runs"] = self.data["runs"][-60:]

    def prune(self, keep_days: int = 400, today: date | None = None) -> None:
        cutoff = (today or date.today()) - timedelta(days=keep_days)
        seen = self.data["seen"]
        for k in list(seen):
            try:
                if datetime.strptime(seen[k]["first_seen"], "%Y-%m-%d").date() < cutoff:
                    del seen[k]
            except (KeyError, ValueError):
                del seen[k]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
