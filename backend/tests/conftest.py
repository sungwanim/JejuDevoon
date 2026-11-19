"""테스트는 합성 스냅샷만 보게 한다. 실데이터를 수집하면 snapshots/live/ 가 생기는데, 그게 기본 레지스트리에 섞이면
(합성 관측소 숨김, 가격 실데이터 대체) 가짜 LLM 시나리오가 깨진다. 최상위 snapshots/*.json 만 임시 폴더로 복사해 기본값으로 쓴다.
테스트 모듈이 import 시점에 SnapshotRegistry()를 만들기도 해서, 픽스처가 아니라 이 파일을 불러올 때 바로 바꾼다."""
import atexit
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from jejuagent.catalog.catalog import ROOT  # noqa: E402
from jejuagent.runner.datasource import SnapshotRegistry  # noqa: E402

_SNAP = Path(tempfile.mkdtemp(prefix="jeju-test-snapshots-"))
atexit.register(shutil.rmtree, _SNAP, ignore_errors=True)
for _f in (ROOT / "snapshots").glob("*.json"):
    shutil.copy(_f, _SNAP)
_orig_init = SnapshotRegistry.__init__


def _init(self, snapshots_dir=None, catalog_dir=None):
    _orig_init(self, snapshots_dir or _SNAP, catalog_dir)


SnapshotRegistry.__init__ = _init
