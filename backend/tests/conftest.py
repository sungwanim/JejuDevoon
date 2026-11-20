"""테스트는 실데이터 대신 테스트용 가짜 스냅샷(synth_fixtures.py)만 보게 한다. 실데이터를 수집하면 snapshots/live/ 가 생기는데,
그게 기본 레지스트리에 섞이면 가짜 LLM 시나리오(고정된 값 기대)가 깨진다. 임시 폴더에 가짜 스냅샷을 써서 기본 폴더로 쓴다.
테스트 모듈이 import 시점에 SnapshotRegistry()를 만들기도 해서, 픽스처가 아니라 이 파일을 불러올 때 바로 바꾼다."""
import atexit
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

sys.path.insert(0, str(Path(__file__).resolve().parent))  # synth_fixtures
from synth_fixtures import write_test_snapshots  # noqa: E402
from jejuagent.runner.datasource import SnapshotRegistry  # noqa: E402

_SNAP = Path(tempfile.mkdtemp(prefix="jeju-test-snapshots-"))
atexit.register(shutil.rmtree, _SNAP, ignore_errors=True)
write_test_snapshots(_SNAP)
_orig_init = SnapshotRegistry.__init__


def _init(self, snapshots_dir=None, catalog_dir=None):
    _orig_init(self, snapshots_dir or _SNAP, catalog_dir)


SnapshotRegistry.__init__ = _init
