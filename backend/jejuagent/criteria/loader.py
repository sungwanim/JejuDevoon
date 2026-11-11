"""작목 재배 기준표 로더. 데이터는 같은 폴더의 criteria.json. 적합도 계산은 하지 않는다(12번 티켓)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_PATH = Path(__file__).with_name("criteria.json")
CROPS = ("당근", "마늘", "무", "양배추", "양파", "감귤")
VALUE_TYPES = {"range", "threshold_min", "threshold_max", "value", "text", "missing"}
MISSING = "미확보"


@dataclass(frozen=True)
class Criterion:
    crop: str
    item: str
    stage: str
    value_type: str
    min: float | None
    max: float | None
    unit: str
    status: str
    source_id: str | None
    location: str | None
    confidence: str
    note: str
    grade: str | None = None
    original_checked: bool | None = None

    @property
    def is_missing(self) -> bool:
        return self.status == MISSING


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    author: str
    publisher: str
    year: str
    url: str
    kind: str


class CriteriaError(ValueError):
    pass


class CriteriaTable:
    def __init__(self, sources: dict[str, Source], records: list[Criterion]):
        self.sources = sources
        self.records = records

    def crops(self) -> list[str]:
        return sorted({r.crop for r in self.records})

    def get(self, crop: str, item: str | None = None, *, grade: str | None = None,
            include_missing: bool = True) -> list[Criterion]:
        """작목(필수), 항목명(선택), 등급(선택)으로 거른다. 모르는 작목이면 KeyError."""
        if crop not in self.crops():
            raise KeyError(f"기준표에 없는 작목: {crop}")
        return [r for r in self.records
                if r.crop == crop
                and (item is None or r.item == item)
                and (grade is None or r.grade == grade)
                and (include_missing or not r.is_missing)]

    def missing(self, crop: str | None = None) -> list[Criterion]:
        return [r for r in self.records if r.is_missing and (crop is None or r.crop == crop)]

    def source_of(self, rec: Criterion) -> Source | None:
        return self.sources.get(rec.source_id) if rec.source_id else None


def _validate(src: dict[str, Source], rec: Criterion) -> None:
    where = f"{rec.crop}/{rec.item}"
    if rec.crop not in CROPS:
        raise CriteriaError(f"{where}: 허용되지 않은 작목")
    if rec.value_type not in VALUE_TYPES:
        raise CriteriaError(f"{where}: value_type 오류 {rec.value_type}")
    if rec.is_missing:
        if rec.value_type != "missing" or rec.min is not None or rec.max is not None or rec.source_id:
            raise CriteriaError(f"{where}: 미확보 항목에 값이나 출처를 넣을 수 없다")
        if not rec.note:
            raise CriteriaError(f"{where}: 미확보 사유(note) 필요")
        return
    if rec.status != "확보" or rec.value_type == "missing":
        raise CriteriaError(f"{where}: status/value_type 불일치")
    if rec.source_id not in src or not rec.location:
        raise CriteriaError(f"{where}: 출처와 위치(쪽·절)가 모두 필요하다")
    if not src[rec.source_id].url:
        raise CriteriaError(f"{where}: 출처 URL 필요")
    need = {"range": (1, 1), "value": (1, 1), "threshold_min": (1, 0), "threshold_max": (0, 1), "text": (0, 0)}[rec.value_type]
    if (rec.min is not None, rec.max is not None) != tuple(bool(n) for n in need):
        raise CriteriaError(f"{where}: {rec.value_type}에 맞지 않는 min/max")
    if rec.min is not None and rec.max is not None and rec.min > rec.max:
        raise CriteriaError(f"{where}: min > max")


def load_criteria(path: str | Path | None = None) -> CriteriaTable:
    raw = json.loads(Path(path or DATA_PATH).read_text(encoding="utf-8"))
    sources = {k: Source(id=k, **v) for k, v in raw["sources"].items()}
    records = [Criterion(**r) for r in raw["records"]]
    for r in records:
        _validate(sources, r)
    return CriteriaTable(sources, records)
