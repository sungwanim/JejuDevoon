"""모듈 저장소: `module_store/<모듈 id>/v<N>/{module.py, meta.json, cache.pkl}`.

- `auto`: 검증을 통과한 생성 코드를 자동 저장 (module_store/). `verified`: 사람이 검토해 `modules_seed/<영역>/*.py` 에 둔 코드 (읽기 전용).
- 시드 파일 하나 = 모듈 하나. MANIFEST의 id·version·verified_by·output_schema 는 선택 키 (id 기본값은 파일 이름).
- 동시성: 단일 사용자 가정. 버전 디렉터리를 mkdir로 선점하고 파일은 임시 파일 + replace로 써서 같은 id 동시 저장이 서로의 파일을 깨지 않게만 한다.
"""
from __future__ import annotations

import json
import os
import pickle
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..sandbox.static_check import check_code
from .privacy import code_has_pii, scrub
from .search import NgramRetriever

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = ROOT / "module_store"
SEED_ROOT = Path(__file__).resolve().parents[1] / "modules_seed"


@dataclass
class Module:
    id: str
    version: int
    status: str                       # verified | auto
    title: str
    description: str                  # 검색용 설명
    tags: list
    input_roles: dict                 # {입력 이름: {역할: dtype}}
    output_schema: list               # [{"id","kind","columns":[{"name","dtype","unit"}]}], 순서가 출력 순서
    params: dict
    validation: dict                  # {"mock": bool, "real": bool, "at": ...}
    tested_on: list                   # [{"dataset_id","version_hash"}]
    model: str
    created: str
    goal: str                         # 원 요청 목표 (개인정보 제거됨)
    code: str
    code_hash: str
    reviewed_by: str = ""

    @property
    def outputs(self) -> list[str]:
        return [o["id"] for o in self.output_schema]

    def meta(self) -> dict:
        d = asdict(self)
        d.pop("code")
        return d


def _slug(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "-", s).strip("-")[:40] or "module"


def _hash(code: str) -> str:
    from ..analysis.tasks import code_hash          # 순환 import를 피하려고 호출 시점에 가져온다
    return code_hash(code)


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class ModuleStore:
    def __init__(self, root: str | Path | None = None, seed_dirs: list | None = None, retriever=None):
        self.root = Path(root) if root else DEFAULT_ROOT
        self.seed_dirs = [Path(d) for d in seed_dirs] if seed_dirs is not None \
            else sorted(p for p in SEED_ROOT.glob("*") if p.is_dir())
        self.retriever = retriever or NgramRetriever()       # 임베딩 검색기로 교체 지점

    # ---- 읽기
    def _seeds(self) -> list[Module]:
        out = []
        for d in self.seed_dirs:
            for p in sorted(d.glob("*.py")):
                if p.name.startswith("_"):
                    continue
                code = p.read_text(encoding="utf-8")
                kind, msgs, mf = check_code(code)
                if kind:
                    raise ValueError(f"시드 모듈 {p} 계약 위반: {msgs}")
                schema = mf.get("output_schema") or [{"id": i, "kind": "", "columns": []} for i in mf["outputs"]]
                out.append(Module(
                    id=mf.get("id") or p.stem, version=int(mf.get("version", 1)), status="verified", title=mf["title"],
                    description=mf["description"], tags=list(mf["tags"]), input_roles=mf["input_roles"],
                    output_schema=schema, params=mf["params"], validation={"mock": True, "real": True, "source": "seed"},
                    tested_on=[], model="", created="", goal="", code=code, code_hash=_hash(code),
                    reviewed_by=mf.get("verified_by", "")))
        return out

    def _stored(self) -> list[Module]:
        out = []
        for mp in sorted(self.root.glob("*/v*/meta.json")):
            meta = json.loads(mp.read_text(encoding="utf-8"))
            out.append(Module(**meta, code=(mp.parent / "module.py").read_text(encoding="utf-8")))
        return out

    def versions(self, module_id: str) -> list[Module]:
        return sorted((m for m in self._seeds() + self._stored() if m.id == module_id), key=lambda m: m.version)

    def all(self) -> list[Module]:
        """모듈 id마다 최신 버전 하나. 같은 id면 verified(시드)가 이긴다."""
        latest: dict[str, Module] = {}
        for m in self._stored() + self._seeds():
            cur = latest.get(m.id)
            if cur is None or (m.status == "verified", m.version) > (cur.status == "verified", cur.version):
                latest[m.id] = m
        return list(latest.values())

    def get(self, module_id: str, version: int | None = None) -> Module | None:
        vs = self.versions(module_id)
        if version is None:
            return vs[-1] if vs else None
        return next((m for m in vs if m.version == version), None)

    # ---- 쓰기
    def save(self, code: str, *, task: dict, tested_on: list, model: str = "", goal: str = "",
             base: Module | None = None) -> Module | None:
        """검증을 통과한 코드를 auto로 저장한다. 같은 코드(해시)가 이미 있으면 새로 만들지 않고 tested_on만 보탠다.
        계약 위반이거나 코드에 개인정보(좌표·키 리터럴)가 있으면 저장하지 않고 None."""
        kind, _, mf = check_code(code)
        if kind or code_has_pii(code):
            return None
        h = _hash(code)
        for m in self._seeds() + self._stored():
            if m.code_hash == h:
                self.add_tested_on(m, tested_on)
                return m
        mid = base.id if base and base.status == "auto" else f"{_slug(mf['title'])}-{h[:6]}"
        outs = [{"id": o["id"], "kind": o["kind"],
                 "columns": [{k: c.get(k, "") for k in ("name", "dtype", "unit")} for c in o["columns"]]}
                for o in task["outputs"]]
        for _ in range(50):                    # 같은 id 동시 저장: mkdir이 원자적이라 먼저 만든 쪽이 번호를 가진다
            nums = [int(p.name[1:]) for p in (self.root / mid).glob("v[0-9]*")]
            v = max(nums, default=0) + 1
            d = self.root / mid / f"v{v}"
            try:
                d.mkdir(parents=True)
                break
            except FileExistsError:
                continue
        else:
            raise OSError(f"모듈 {mid} 버전 디렉터리를 만들지 못했다")
        m = Module(id=mid, version=v, status="auto", title=scrub(mf["title"]), description=scrub(mf["description"]),
                   tags=[scrub(str(t)) for t in mf["tags"]], input_roles=mf["input_roles"], output_schema=outs,
                   params=mf["params"], validation={"mock": True, "real": True, "at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                   tested_on=list(tested_on), model=model, created=time.strftime("%Y-%m-%d"), goal=scrub(goal),
                   code=code, code_hash=h)
        _write(d / "module.py", code)
        _write(d / "meta.json", json.dumps(m.meta(), ensure_ascii=False, indent=1))   # meta가 마지막: 있으면 완성된 버전
        return m

    def add_tested_on(self, m: Module, tested_on: list) -> None:
        """재검증을 통과한 데이터 버전을 auto 모듈의 기록에 보탠다 (verified 시드는 파일이라 건드리지 않는다)."""
        mp = self.root / m.id / f"v{m.version}" / "meta.json"
        if m.status != "auto" or not mp.exists():
            return
        meta = json.loads(mp.read_text(encoding="utf-8"))
        new = [t for t in tested_on if t not in meta["tested_on"]]
        if new:
            meta["tested_on"] += new
            _write(mp, json.dumps(meta, ensure_ascii=False, indent=1))

    # ---- 결과 캐시 (버전당 1칸). 키가 다르면(= 데이터 버전 해시나 매핑이 바뀜) 버린다.
    def cache_get(self, m: Module, key: str):
        p = self.root / m.id / f"v{m.version}" / "cache.pkl"
        if not p.exists():
            return None
        try:
            d = pickle.loads(p.read_bytes())
            if d["key"] == key:
                return d["outputs"]
        except Exception:
            pass
        p.unlink(missing_ok=True)
        return None

    def cache_put(self, m: Module, key: str, outputs: dict) -> None:
        d = self.root / m.id / f"v{m.version}"
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "cache.pkl.tmp"
        tmp.write_bytes(pickle.dumps({"key": key, "outputs": outputs}))
        os.replace(tmp, d / "cache.pkl")
