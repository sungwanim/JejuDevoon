"""② 데이터 선택의 스키마와 코드 규칙 (티켓 04). LLM은 후보를 고르고, 규칙이 결과를 수정·보완한다."""
from __future__ import annotations

import re

REASON_CODES = ["irrelevant", "granularity_mismatch", "out_of_region", "out_of_period", "missing_columns"]
POINT_UNITS = {"point", "grid", "station", "관측소", "격자", "지점"}
AGGREGATE_UNITS = {"시도", "도 전체"}   # 지점 분석에는 못 쓰고 보조로만
MAX_CANDIDATES, KEEP_CANDIDATES = 30, 20


def selection_schema(ids: list[str]) -> dict:
    """데이터셋 id는 enum으로 제한한다 (없는 id는 만들 수 없다)."""
    _id = {"enum": ids}
    _s = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "feasible": {"type": "boolean"},
            "selected": {"type": "array", "items": {
                "type": "object",
                "properties": {"dataset_id": _id, "reason": _s, "columns": {"type": "array", "items": _s}},
                "required": ["dataset_id", "reason", "columns"], "additionalProperties": False}},
            "excluded": {"type": "array", "items": {
                "type": "object",
                "properties": {"dataset_id": _id, "reason_code": {"enum": REASON_CODES}, "note": _s},
                "required": ["dataset_id", "reason_code", "note"], "additionalProperties": False}},
            "unanswerable": {"type": "array", "items": {
                "type": "object", "properties": {"sub_question": _s, "reason": _s},
                "required": ["sub_question", "reason"], "additionalProperties": False}},
            "infeasible_reason": _s,
            "needed_data": {"type": "array", "items": _s},
            "relation": {"type": "object", "properties": {"asked": {"type": "boolean"}, "plausible": {"type": "boolean"}, "reason": _s},
                         "required": ["asked", "plausible", "reason"], "additionalProperties": False},
        },
        "required": ["feasible", "selected", "excluded", "unanswerable", "infeasible_reason", "needed_data", "relation"],
        "additionalProperties": False,
    }


def summarize(entry: dict) -> dict:
    """LLM에 보낼 카탈로그 요약. 데이터 값·notes 같은 본문은 보내지 않는다."""
    return {"id": entry["id"], "title": entry.get("title"), "source": entry.get("source"), "synthetic": bool(entry.get("synthetic")),
            "spatial_unit": entry.get("spatial_unit"), "temporal_unit": entry.get("temporal_unit"),
            "coverage": entry.get("coverage"),
            "columns": [{"name": c["name"], "meaning": c.get("meaning", ""), "unit": c.get("unit", "")}
                        for c in entry.get("columns", [])]}


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text.lower())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def reduce_candidates(plan: dict, catalog: list[dict]) -> list[dict]:
    """카탈로그가 30개를 넘으면 글자 2-gram 겹침으로 상위 20개만 남긴다. shortcut: 임베딩이 아님, 모듈 검색은 07."""
    if len(catalog) <= MAX_CANDIDATES:
        return catalog
    q = _bigrams(" ".join([plan.get("goal") or "", plan.get("crop") or "", *plan.get("sub_questions", []),
                           *plan.get("tags", []), (plan.get("location") or {}).get("text") or ""]))

    def score(e):
        doc = " ".join([e.get("title") or "", e.get("source") or "",
                        *(c["name"] + c.get("meaning", "") for c in e.get("columns", []))])
        return len(q & _bigrams(doc))
    return sorted(catalog, key=score, reverse=True)[:KEEP_CANDIDATES]


def _years(text: str | None) -> tuple[int, int] | None:
    ys = [int(y) for y in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text or "")]
    return (min(ys), max(ys)) if ys else None


def out_of_period(plan: dict, entry: dict) -> str | None:
    want, cov = _years(plan.get("period")), entry.get("coverage") or {}
    have = _years(f"{cov.get('from', '')} {cov.get('to', '')}")
    if want and have and (want[1] < have[0] or want[0] > have[1]):
        return f"요청 기간 {want[0]}~{want[1]}년과 데이터 기간 {have[0]}~{have[1]}년이 겹치지 않습니다."
    return None


_CITIES = ("제주시", "서귀포시")


def out_of_region(plan: dict, entry: dict) -> str | None:
    """요청 지역(제주시/서귀포시)이 데이터 범위의 시와 다르면 사유. shortcut: 글자 비교만, 좌표→시 판정은 안 함."""
    text = (plan.get("location") or {}).get("text") or ""
    region = (entry.get("coverage") or {}).get("region") or ""
    want = next((c for c in _CITIES if c in text), None)
    if want and any(c in region for c in _CITIES) and want not in region:
        return f"이 데이터는 {region}만 포함하고 {want} 데이터는 없습니다."
    return None


def apply_rules(plan: dict, catalog: list[dict], candidates: list[dict], llm_out: dict) -> dict:
    """LLM 결과 + 규칙 -> Selection. 규칙이 LLM의 선택을 뒤집을 수 있다."""
    by_id = {e["id"]: e for e in catalog}
    selected: dict[str, dict] = {}
    excluded: dict[str, dict] = {}
    for s in llm_out.get("selected", []):
        if s["dataset_id"] in by_id:  # 스키마 enum이 막지만 어댑터가 달라도 한 번 더 막는다
            selected.setdefault(s["dataset_id"], {"dataset_id": s["dataset_id"], "reason": s.get("reason", ""),
                                                  "columns": list(s.get("columns") or []), "role": "primary"})
    for x in llm_out.get("excluded", []):
        if x["dataset_id"] in by_id and x["dataset_id"] not in selected:
            excluded.setdefault(x["dataset_id"], {"dataset_id": x["dataset_id"], "reason_code": x["reason_code"],
                                                  "note": x.get("note", ""), "by": "llm"})
    unanswered = [{"what": u["sub_question"], "why": u["reason"]} for u in llm_out.get("unanswerable", [])]

    def drop(did, code, note):
        selected.pop(did, None)
        excluded[did] = {"dataset_id": did, "reason_code": code, "note": note, "by": "rule"}

    needs = plan.get("needs") or {}
    for did in list(selected):
        e = by_id[did]
        if msg := out_of_period(plan, e):
            drop(did, "out_of_period", msg)
        elif msg := out_of_region(plan, e):
            drop(did, "out_of_region", msg)
            unanswered.append({"what": f"{e.get('title')} 관련 질문", "why": msg})
        else:
            names = {c["name"] for c in e.get("columns", [])}
            want = selected[did]["columns"]
            ok = [c for c in want if c in names]
            if want and not ok:
                drop(did, "missing_columns", f"요청한 컬럼 {want}이(가) 데이터에 없습니다.")
            else:
                selected[did]["columns"] = ok

    if needs.get("point_analysis"):
        # 시도·도 전체 단위는 지점 분석의 보조로만: 보조가 아닌 데이터가 하나도 없으면 같이 뺀다.
        main = [d for d in selected if by_id[d].get("spatial_unit") not in AGGREGATE_UNITS]
        for d in list(selected):
            if by_id[d].get("spatial_unit") in AGGREGATE_UNITS:
                if main:
                    selected[d]["role"] = "auxiliary"
                else:
                    drop(d, "granularity_mismatch", "시도·도 전체 단위 데이터만으로는 지점 분석을 할 수 없습니다(보조로만 사용).")
        if not any(by_id[d].get("spatial_unit") in POINT_UNITS for d in selected):
            unanswered.append({"what": "지점 단위 분석",
                               "why": "지점·격자·관측소 단위 데이터가 없어 해당 지점의 값을 직접 구할 수 없습니다."})

    for e in catalog:  # LLM이 아무 말도 안 한 데이터는 관련 없음으로 기록
        if e["id"] not in selected and e["id"] not in excluded:
            cut = e["id"] not in {c["id"] for c in candidates}
            excluded[e["id"]] = {"dataset_id": e["id"], "reason_code": "irrelevant", "by": "rule",
                                 "note": "후보 축소에서 제외됨" if cut else "선택되지 않음"}

    answerable = bool(selected)
    needed = list(llm_out.get("needed_data") or [])
    why = llm_out.get("infeasible_reason") or ""
    if not answerable:
        why = why or "요청에 쓸 수 있는 데이터가 없습니다."
        if not needed:
            needed = _needed_from(plan)
    uq = {u["what"] for u in unanswered}
    subs = [{"question": q, "status": "unanswered" if q in uq else "planned",
             "why": next((u["why"] for u in unanswered if u["what"] == q), "")}
            for q in plan.get("sub_questions", [])]
    return {"feasible": answerable, "selected": list(selected.values()), "excluded": list(excluded.values()),
            "unanswered": unanswered, "sub_questions": subs,
            "infeasible_reason": "" if answerable else why, "needed_data": [] if answerable else needed}


def _needed_from(plan: dict) -> list[str]:
    loc = (plan.get("location") or {}).get("text") or "요청 지역"
    parts = [p for p in (plan.get("crop"), loc, plan.get("period")) if p]
    out = [f"{' · '.join(parts)}에 해당하는 데이터" if parts else "요청 주제에 해당하는 데이터"]
    if (plan.get("needs") or {}).get("point_analysis"):
        out.append("지점·격자·관측소 단위 데이터")
    return out
