"""데이터 소스 레지스트리 인터페이스 (카탈로그 id -> 데이터). 03이 구현을 채운다."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class DatasetNotFound(KeyError):
    pass


class DataSourceRegistry(ABC):
    @abstractmethod
    def catalog(self) -> list[dict]:
        """카탈로그 요약 목록 (id, title, source, 공간·시간 단위, 범위, 컬럼). 빈 목록 가능."""

    @abstractmethod
    def load(self, dataset_id: str):
        """카탈로그 id의 데이터(pandas.DataFrame)를 돌려준다. 실패하면 예외 (③이 처리)."""


class EmptyRegistry(DataSourceRegistry):
    """카탈로그가 비어 있는 기본 구현."""

    def catalog(self) -> list[dict]:
        return []

    def load(self, dataset_id: str):
        raise DatasetNotFound(dataset_id)


class SnapshotRegistry(DataSourceRegistry):
    """카탈로그 JSON(catalog/)과 파일·스냅샷(data/, snapshots/)을 읽는 구현. 라이브 API는 09가 추가."""

    def __init__(self, snapshots_dir: str | Path | None = None, catalog_dir: str | Path | None = None):
        from ..catalog.catalog import ROOT
        self.snapshots_dir = Path(snapshots_dir) if snapshots_dir else ROOT / "snapshots"
        self.catalog_dir = Path(catalog_dir) if catalog_dir else ROOT / "catalog"
        self.root = ROOT if catalog_dir is None else self.catalog_dir.parent

    def catalog(self) -> list[dict]:
        """optional 항목은 스냅샷 파일이 있을 때만 보인다(수집 전에는 로드 실패하는 데이터를 고르지 않게)."""
        from ..catalog.catalog import load_catalog
        cat = load_catalog(self.catalog_dir)
        shown = {e["id"] for e in cat if not e.get("optional") or (self.snapshots_dir / e.get("snapshot", "")).is_file()}
        return [e for e in cat if e["id"] in shown]

    def load(self, dataset_id: str):
        from ..catalog.loader import load_dataset
        entry = next((e for e in self.catalog() if e["id"] == dataset_id), None)
        if entry is None:
            raise DatasetNotFound(dataset_id)
        return load_dataset(entry, self.root, self.snapshots_dir)


def make_registry() -> DataSourceRegistry:
    """JEJU_DATA_MODE=live 이면 라이브 호출 + 스냅샷 폴백, 아니면 스냅샷만 (기본). api/main.py가 쓰도록 연결하는 것은 01의 몫."""
    import os
    if os.environ.get("JEJU_DATA_MODE") == "live":
        from ..data.live import LiveRegistry
        return LiveRegistry()
    return SnapshotRegistry()
