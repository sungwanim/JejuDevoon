"""실행 기록(trace). runs/{run_id}/trace.json 에 저장한다."""
from __future__ import annotations

import json
import time
from pathlib import Path


class Trace:
    def __init__(self, run_id: str, runs_dir: str | Path | None):
        self.run_id = run_id
        self.dir = Path(runs_dir) / run_id if runs_dir else None
        self.events: list[dict] = []
        self._t0 = time.monotonic()
        self.listener = None   # thought 이벤트가 생길 때 부르는 함수(화면이 진행 중에도 생각 과정을 받게 한다)

    def add(self, type: str, **fields) -> dict:
        ev = {"type": type, "t": round(time.monotonic() - self._t0, 3), **fields}
        self.events.append(ev)
        if type == "thought" and self.listener:
            self.listener()
        return ev

    def save(self, state_dict: dict, html: str | None = None) -> Path | None:
        """trace.json (+ 결과 HTML)을 쓴다. 단계마다 호출되어 진행 중에도 파일이 남는다."""
        if self.dir is None:
            return None
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / "trace.json"
        path.write_text(json.dumps({"run_id": self.run_id, "state": state_dict, "events": self.events},
                                   ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        if html:
            (self.dir / "result.html").write_text(html, encoding="utf-8")
        return path
