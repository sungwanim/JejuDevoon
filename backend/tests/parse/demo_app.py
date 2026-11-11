"""화면 확인용 데모 서버 (테스트 아님): uvicorn demo_app:app --app-dir backend/tests/parse. 키워드로 계획을 흉내낸다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jejuagent.api.app import create_app  # noqa: E402
from jejuagent.llm import FakeLLM  # noqa: E402


def _respond(system, user):
    point = "적합" in user
    has = "[클릭 좌표]" in user
    return {"goal": user[:30], "sub_questions": ["a", "b"],
            "needs": {"point_analysis": point, "time_series": False, "spatial_comparison": False},
            "location": {"kind": "none", "text": None, "lat": None, "lon": None},
            "crop": None, "period": None, "style": "unspecified",
            "missing": ["위치"] if point and not has else [], "clarify_question": "어느 위치인가요? 지도를 클릭하세요.",
            "in_domain": "주식" not in user, "domain_reason": "범위 밖", "profit_guarantee": False, "tags": []}


app = create_app(lambda: FakeLLM([_respond] * 50))
