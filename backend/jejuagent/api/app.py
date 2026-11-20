"""FastAPI: 실행 시작, 상태·결과 조회, 카탈로그 목록. 실행은 백그라운드 스레드에서 돈다."""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..llm.base import LLMClient
from ..runner import DataSourceRegistry, EmptyRegistry, run_agent
from ..runner.runner import DEFAULT_RUNS_DIR

DEFAULT_WEB_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"   # npm run build 결과
NO_WEB = "화면이 빌드되지 않았습니다. frontend 폴더에서 `npm install` 후 `npm run build` 를 실행하세요. (API는 정상 동작 중)"


class RunRequest(BaseModel):
    request: str
    lat: float | None = None
    lon: float | None = None
    conversation_id: str | None = None   # 되묻기 이어쓰기: 이전 실행의 대화 상태를 이어 받는다


def create_app(llm_factory: Callable[[], LLMClient], data: DataSourceRegistry | None = None,
               runs_dir: str | Path | None = DEFAULT_RUNS_DIR, modules=None,
               web_dir: str | Path | None = DEFAULT_WEB_DIR) -> FastAPI:
    app = FastAPI(title="제주 공공데이터 분석 Agent")
    registry = data or EmptyRegistry()
    runs: dict[str, dict] = {}                 # run_id -> {"state": dict, "events": list, "done": bool}
    conversations: dict[str, dict] = {}        # conversation_id -> prev(되묻기 이전 상태)
    lock = threading.Lock()

    def progress(run_id):
        def cb(state, trace):
            with lock:
                runs[run_id].update(state=state.to_dict(), events=list(trace.events))
        return cb

    def worker(run_id: str, body: RunRequest, prev: dict | None):
        click = {"lat": body.lat, "lon": body.lon} if body.lat is not None and body.lon is not None else None
        try:
            res = run_agent(body.request, llm=llm_factory(), data=registry, click=click, prev=prev,
                            runs_dir=runs_dir, run_id=run_id, on_progress=progress(run_id), modules=modules)
            if res.status == "clarify" and body.conversation_id:
                conversations[body.conversation_id] = {"plan": res.state.plan, "request": body.request}
        except Exception as e:  # llm_factory 실패 등. run_agent 안의 오류는 이미 failed로 처리됨
            with lock:
                runs[run_id]["state"] = {"status": "failed", "reason": str(e), "message": str(e), "stage": "done"}
        finally:
            runs[run_id]["done"] = True

    @app.post("/api/runs")
    def start_run(body: RunRequest):
        if not body.request.strip():
            raise HTTPException(400, "요청 문장이 비어 있습니다.")
        run_id = uuid.uuid4().hex[:12]
        prev = conversations.pop(body.conversation_id, None) if body.conversation_id else None
        runs[run_id] = {"state": {"status": None, "stage": "queued"}, "events": [], "done": False}
        threading.Thread(target=worker, args=(run_id, body, prev), daemon=True).start()
        return {"run_id": run_id}

    def get(run_id: str) -> dict:
        if run_id not in runs:
            raise HTTPException(404, "알 수 없는 실행입니다.")
        return runs[run_id]

    @app.get("/api/runs/{run_id}")
    def run_status(run_id: str):
        r, s = get(run_id), get(run_id)["state"]
        thoughts = [{"stage": e["stage"], "text": e["text"], "t": e["t"]} for e in r["events"] if e["type"] == "thought"]
        return {"run_id": run_id, "running": not r["done"], "stage": s.get("stage"), "status": s.get("status"),
                "reason": s.get("reason", ""), "message": s.get("message", ""), "thoughts": thoughts}

    @app.get("/api/runs/{run_id}/result")
    def run_result(run_id: str):
        r = get(run_id)
        s = r["state"]
        return {"run_id": run_id, "running": not r["done"], "status": s.get("status"), "reason": s.get("reason", ""),
                "message": s.get("message", ""), "needed_data": s.get("needed_data", []),
                "html": s.get("html"), "unanswered": s.get("unanswered", []),
                "notices": (s.get("extra") or {}).get("notices", []),
                "state": s, "events": r["events"]}

    @app.get("/api/catalog")
    def catalog():
        return registry.catalog()

    # 빌드된 화면을 같은 포트로 서빙한다. /api 라우트가 먼저 등록돼 있어 가려지지 않고, 없는 /api/... 는 404.
    if web_dir and (Path(web_dir) / "index.html").is_file():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    else:
        @app.get("/")
        def no_web():
            return {"message": NO_WEB}

    return app
