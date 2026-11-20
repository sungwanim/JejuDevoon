"""⑤ 렌더 패키지 (티켓 08): ReportSpec 구조화 출력 -> 숫자 근거 대조 -> Jinja2 HTML."""
from __future__ import annotations

from ..llm.base import LLMError
from .html import render_html  # noqa: F401
from .numbers import check_sentence, extract_numbers, grounded_numbers  # noqa: F401
from .spec import REPORT_SPEC_SCHEMA, SYSTEM, fallback_spec, sanitize, user_prompt


def build_html(state, ctx) -> tuple[str, dict]:
    """(html, info). info: removed(근거 없어 뺀 문장), fallback(LLM 없이 렌더했는가), reason."""
    from ..runner.context import LimitExceeded  # 지연 import: runner가 이 패키지를 먼저 import한다
    plan = state.plan or {}
    removed: list[str] = []
    spec, fallback, reason = None, False, ""
    if state.artifacts and not ctx.disabled:
        try:
            raw = ctx.llm.structured(SYSTEM, user_prompt(state), REPORT_SPEC_SCHEMA, schema_name="report_spec",
                                     purpose="s5_report_spec").data
            g = grounded_numbers(state.artifacts, [state.request, plan.get("goal") or "", plan.get("period") or "",
                                                   *plan.get("sub_questions", [])],
                                 _counts(state))
            spec = sanitize(raw, state.artifacts, g, removed)
        except LimitExceeded as e:
            reason = f"limit:{e.which}"
        except LLMError as e:
            reason = f"llm_error:{e}"
    else:
        reason = "limit" if ctx.disabled else "no_artifacts"
    if spec is None or not (spec["summary"] or spec["sections"]):
        spec, fallback = fallback_spec(state), True
    loc = plan.get("location") or {}
    return render_html(state, spec, ctx.data.catalog(), removed, fallback), \
        {"removed": removed, "fallback": fallback, "reason": reason, "location": loc}


def _counts(state) -> list[float]:
    sel = state.selection or {}
    return [len(sel.get("selected", [])), len(sel.get("excluded", [])), len(state.tasks), len(state.artifacts),
            len(state.unanswered), *[len(t.get("attempts", [])) for t in state.tasks],
            *[(state.plan or {}).get("location", {}).get(k) or 0 for k in ("lat", "lon")]]
