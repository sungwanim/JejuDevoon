"""중간산출물. state.artifacts[id] 에 저장된다 (08 렌더, 07 모듈 라이브러리가 읽는다).

shape 속성이 있어 RunState.to_dict()가 `<Artifact shape=(65, 3)>` 요약 문자열로 바꿔 trace에 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Artifact:
    id: str
    kind: str                      # table | series | geo (DataFrame) | metrics (dict)
    value: Any                     # DataFrame 또는 dict
    description: str
    columns: list[dict]            # 설계한 컬럼 [{"name","dtype","unit"}] (metrics는 [])
    source_ids: list[str]          # 출처: 입력 데이터 id 또는 앞 작업의 중간산출물 id
    task_id: str
    module_title: str              # 코드의 MANIFEST["title"]
    code_hash: str                 # 정규화한 코드의 sha256 앞 16자
    code: str                      # 검증을 통과한 코드 (07이 모듈로 저장할 때 쓴다)
    role_mapping: dict = field(default_factory=dict)   # {입력 이름: {역할: 실제 컬럼}}

    @property
    def shape(self) -> tuple:
        return tuple(self.value.shape) if hasattr(self.value, "shape") else (len(self.value),)

    def summary(self) -> dict:
        """JSON 저장용 요약 (값 없음)."""
        return {"id": self.id, "kind": self.kind, "description": self.description, "shape": list(self.shape),
                "columns": self.columns, "source_ids": self.source_ids, "task_id": self.task_id,
                "module_title": self.module_title, "code_hash": self.code_hash}
