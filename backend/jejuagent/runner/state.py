"""RunState: 한 번의 실행에서 단계들이 차례로 갱신하는 하나의 상태 객체."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

STATUSES = ("answered", "partial", "clarify", "infeasible", "failed")


@dataclass
class RunState:
    run_id: str
    request: str                                  # 사용자 요청 문장
    click: dict | None = None                     # {"lat":..,"lon":..} 지도 클릭 좌표
    prev: dict | None = None                      # 되묻기 이전 대화 상태 (이전 RequestPlan 등)

    # --- 종료 ---
    status: str | None = None                     # STATUSES 중 하나. 단계가 정하면 러너가 거기서 멈춘다
    reason: str = ""                              # 불가/실패 이유, 되묻기 질문 1개
    message: str = ""                             # 사용자에게 보일 안내문
    needed_data: list[str] = field(default_factory=list)   # infeasible일 때 필요한 데이터 안내
    html: str | None = None                       # 최종 HTML (⑤)
    unanswered: list[dict] = field(default_factory=list)   # 답하지 못한 부분 [{"what","why"}]
    limit_hit: str | None = None                  # "llm_calls" | "time": 상한에 걸렸을 때

    # --- 단계별 산출물 (내용 형식은 각 단계 티켓이 정한다) ---
    plan: dict | None = None                      # ① RequestPlan (+ output_format)
    selection: dict | None = None                 # ② Selection
    data: dict[str, Any] = field(default_factory=dict)       # ③ dataset_id -> DataFrame (저장 시 요약만)
    profiles: dict[str, dict] = field(default_factory=dict)  # ③ dataset_id -> Profile
    load_failures: list[dict] = field(default_factory=list)  # ③ [{"dataset_id","error"}]
    tasks: list[dict] = field(default_factory=list)          # ④ 작업 목록 + 시도 기록
    artifacts: dict[str, Any] = field(default_factory=dict)  # ④ 중간산출물 id -> 값
    stage: str = ""                               # 현재(마지막) 단계 이름
    extra: dict[str, Any] = field(default_factory=dict)      # 후속 티켓이 자유롭게 쓰는 자리

    def finish(self, status: str, reason: str = "", message: str = "") -> None:
        assert status in STATUSES, status
        self.status, self.reason, self.message = status, reason, message or reason

    def to_dict(self) -> dict:
        """JSON 저장용. DataFrame 등은 요약 문자열로 바꾼다."""
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["data"] = {k: _summ(v) for k, v in self.data.items()}
        d["artifacts"] = {k: _summ(v) for k, v in self.artifacts.items()}
        return d


def _summ(v: Any) -> Any:
    if hasattr(v, "shape"):
        return f"<{type(v).__name__} shape={tuple(v.shape)}>"
    return v
