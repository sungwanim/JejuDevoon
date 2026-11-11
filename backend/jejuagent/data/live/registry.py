"""라이브 호출 + 스냅샷 폴백 레지스트리.

df.attrs["data_mode"]: "live"(방금 API로 받음) | "snapshot"(고정된 파일/스냅샷) | "fallback"(라이브 시도가 실패해 스냅샷 사용).
fallback이면 df.attrs["fallback_reason"] = {kind, cause, fix, detail} (사용자에게 보여줄 한국어 원인·해결 방법).
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from ...catalog.loader import load_dataset
from ...runner.datasource import DatasetNotFound, SnapshotRegistry
from .errors import LiveError
from .hub import API_ID, CULTIVARS, HubClient
from .snapshot import save_snapshot

log = logging.getLogger(__name__)
MA_PERIOD = 7  # 카탈로그의 이동평균 컬럼은 7일 기준


class LiveRegistry(SnapshotRegistry):
    def __init__(self, *args, live: bool = True, hub: HubClient | None = None, start: str | None = None,
                 end: str | None = None, **kw):
        super().__init__(*args, **kw)
        self.live, self._hub = live, hub
        today = date.today()
        self.start = start or (today - timedelta(days=365)).strftime("%Y%m%d")
        self.end = end or today.strftime("%Y%m%d")
        self.notices: list[dict] = []   # 폴백이 일어날 때마다 {dataset_id, ...as_dict}

    def load(self, dataset_id: str):
        entry = next((e for e in self.catalog() if e["id"] == dataset_id), None)
        if entry is None:
            raise DatasetNotFound(dataset_id)
        api = next((k for k, v in API_ID.items() if v in entry.get("live_api", "")), None)
        if not (self.live and api):
            return self._from_snapshot(entry, "snapshot")
        try:
            rows = self._fetch_hub(api)
        except LiveError as e:
            log.warning("라이브 실패 %s: %s (%s)", dataset_id, e.kind, e.detail)
            self.notices.append({"dataset_id": dataset_id, **e.as_dict()})
            return self._from_snapshot(entry, "fallback", e)
        save_snapshot(dataset_id, rows, {"source": entry.get("source", ""), "range": [self.start, self.end]}, self.snapshots_dir / "live")
        return self._from_snapshot(entry, "live")

    def _fetch_hub(self, api: str) -> list[dict]:
        hub = self._hub or HubClient()
        rows: list[dict] = []
        for c in CULTIVARS:
            rows += hub.fetch(api, self.start, self.end, c, period=MA_PERIOD if api == "moving_avg" else None)
        return rows

    def _from_snapshot(self, entry: dict, mode: str, err: LiveError | None = None):
        real = self.snapshots_dir / "live" / f"{entry['id']}.json"
        e = {**entry, "snapshot": f"live/{entry['id']}.json"} if real.exists() else entry   # 실데이터 스냅샷이 있으면 그것을 우선
        df = load_dataset(e, self.root, self.snapshots_dir)
        df.attrs["data_mode"] = mode
        if err:
            df.attrs["fallback_reason"] = err.as_dict()
        if "snapshot" in e:
            meta = json.loads((self.snapshots_dir / e["snapshot"]).read_text(encoding="utf-8")).get("meta", {})
            df.attrs["snapshot_version"] = meta.get("version_hash", "")
        return df
