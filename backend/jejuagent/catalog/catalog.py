"""카탈로그 JSON(catalog/{id}.json) 읽기. 형식은 DESIGN.md §3."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]   # 프로젝트 루트 (catalog/, snapshots/, data/가 있는 곳)


def load_catalog(catalog_dir: str | Path | None = None) -> list[dict]:
    d = Path(catalog_dir) if catalog_dir else ROOT / "catalog"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]
