"""uvicorn 진입점: `uvicorn jejuagent.api.main:app` (backend/ 에서). 키는 .env에서만 읽는다.

JEJU_LLM=fake 이면 키 없이 화면을 확인하는 데모용 가짜 LLM을 쓴다 (파이프라인 진행 화면만 보여 주고, 데이터 선택에서 "데모라 분석 불가"로 끝낸다).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

from ..llm import FakeLLM, OpenAILLM
from ..modules_lib import ModuleStore
from ..runner.datasource import make_registry
from .app import create_app

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


def _demo_fake() -> FakeLLM:
    plan = {"goal": "데모 요청", "sub_questions": [], "needs": {"point_analysis": False, "time_series": False, "spatial_comparison": False},
            "location": {"kind": "none", "text": None, "lat": None, "lon": None}, "crop": None, "period": None,
            "style": "unspecified", "missing": [], "clarify_question": None, "profit_guarantee": False, "tags": []}
    nodata = {"feasible": False, "selected": [], "excluded": [], "unanswerable": [], "needed_data": ["실제 LLM 키"],
              "infeasible_reason": "데모 모드(JEJU_LLM=fake)라 실제 분석은 하지 않습니다."}
    return FakeLLM([lambda system, user: plan if "요청 규격화 담당" in system else nodata] * 100)


app = create_app(_demo_fake if os.environ.get("JEJU_LLM") == "fake" else OpenAILLM, data=make_registry(), modules=ModuleStore())
