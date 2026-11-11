"""수집한 데이터를 버전 해시와 함께 snapshots/live/ 에 고정한다. 형식은 03의 스냅샷과 같다: {"meta": {...}, "data": [...]}."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ...catalog.catalog import ROOT

LIVE_DIR = ROOT / "snapshots" / "live"


def version_hash(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def save_snapshot(name: str, rows: list[dict], meta: dict | None = None, directory: Path | None = None) -> Path:
    d = Path(directory) if directory else LIVE_DIR
    d.mkdir(parents=True, exist_ok=True)
    m = {**(meta or {}), "synthetic": False, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "n_rows": len(rows), "version_hash": version_hash(rows)}
    p = d / f"{name}.json"
    p.write_text(json.dumps({"meta": m, "data": rows}, ensure_ascii=False), encoding="utf-8")
    return p
