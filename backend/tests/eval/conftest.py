import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "backend", ROOT / "eval"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """사용자의 실제 .env(키)가 테스트로 새어 들어오지 않게 한다. 이 테스트들은 어떤 경우에도 OpenAI를 부르지 않는다."""
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    for k in ("OPENAI_API_KEY", "JEJU_HUB_PROJECT_KEY", "DATA_GO_KR_SERVICE_KEY"):
        monkeypatch.delenv(k, raising=False)
