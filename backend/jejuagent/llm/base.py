"""LLM 어댑터 인터페이스. 모든 LLM 호출은 이 인터페이스를 통해서만 한다 (OpenAI / 가짜 교체 가능)."""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


class LLMError(Exception):
    """LLM 호출 실패(키 없음, 네트워크 등). 러너가 failed로 처리한다."""


@dataclass
class CallInfo:
    """실행 기록(trace)에 남는 호출 정보. 프롬프트 원문은 남기지 않고 해시만 둔다."""
    kind: str                 # "structured" | "text"
    model: str
    prompt_hash: str
    input_tokens: int = 0
    output_tokens: int = 0
    ms: int = 0
    purpose: str = ""         # 호출 목적(단계 이름 등). 호출한 쪽이 붙인다.

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LLMResponse:
    """structured 호출이면 data, text 호출이면 text가 채워진다."""
    info: CallInfo
    data: dict | None = None
    text: str | None = None


def prompt_hash(system: str, user: str, schema: dict | None = None) -> str:
    raw = json.dumps([system, user, schema], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class LLMClient(ABC):
    @abstractmethod
    def structured(self, system: str, user: str, schema: dict, *,
                   schema_name: str = "result", purpose: str = "") -> LLMResponse:
        """JSON 스키마를 만족하는 구조화 응답(Structured Outputs). schema는 JSON Schema dict."""

    @abstractmethod
    def text(self, system: str, user: str, *, purpose: str = "") -> LLMResponse:
        """자유 텍스트 응답."""
