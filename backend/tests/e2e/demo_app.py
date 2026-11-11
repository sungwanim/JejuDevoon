"""화면 확인용 데모 서버 (테스트 아님): backend/ 에서 `uvicorn demo_app:app --app-dir tests/e2e --port 8000`.
fakes.respond 로 지점 질문 전체 경로를 흉내낸다 (지도 클릭 + "여기에 월동무 어때? 최근 시세도 같이 알려줘" 등). 모듈 저장소·실행 기록은 임시 폴더."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import make_llm  # noqa: E402

from jejuagent.api.app import create_app  # noqa: E402
from jejuagent.modules_lib import ModuleStore  # noqa: E402
from jejuagent.runner.datasource import SnapshotRegistry  # noqa: E402

app = create_app(make_llm, data=SnapshotRegistry(), modules=ModuleStore(Path(tempfile.mkdtemp()) / "store"),
                 runs_dir=Path(tempfile.mkdtemp()))
