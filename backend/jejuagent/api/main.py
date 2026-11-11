"""uvicorn 진입점: `uvicorn jejuagent.api.main:app` (backend/ 에서). 키는 .env에서만 읽는다.

JEJU_LLM=fake 이면 키 없이 화면을 확인하는 데모용 가짜 LLM을 쓴다 (도메인 판정을 키워드로 흉내).
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
    off = ("주식", "코인", "비트코인", "날씨 어때")

    def respond(system, user):
        bad = any(w in user for w in off)
        return {"in_domain": not bad, "reason": "제주 농업·기후·시장 데이터 분석과 관련 없는 요청입니다." if bad else ""}
    return FakeLLM([respond] * 100)


app = create_app(_demo_fake if os.environ.get("JEJU_LLM") == "fake" else OpenAILLM, data=make_registry(), modules=ModuleStore())
