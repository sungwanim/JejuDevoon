"""RequestPlan 스키마와 코드 규칙 (티켓 02). LLM은 계획만 내고, 형식·되묻기·범위 판정은 여기 규칙이 정한다."""
from __future__ import annotations

_S = {"type": "string"}
_NS = {"type": ["string", "null"]}
_NN = {"type": ["number", "null"]}

REQUEST_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": _S,                                    # 정규화된 목표 한 문장
        "sub_questions": {"type": "array", "items": _S},  # LLM이 직접 분해한 하위 질문
        "needs": {                                     # 필요한 성격
            "type": "object",
            "properties": {"point_analysis": {"type": "boolean"}, "time_series": {"type": "boolean"},
                           "spatial_comparison": {"type": "boolean"}},
            "required": ["point_analysis", "time_series", "spatial_comparison"],
            "additionalProperties": False,
        },
        "location": {
            "type": "object",
            "properties": {"kind": {"enum": ["point", "region", "none"]}, "text": _NS, "lat": _NN, "lon": _NN},
            "required": ["kind", "text", "lat", "lon"],
            "additionalProperties": False,
        },
        "crop": _NS,
        "period": _NS,
        "style": {"enum": ["report", "easy", "unspecified"]},   # 보고서 / 쉬운 설명
        "missing": {"type": "array", "items": _S},     # 빠진 필수 정보 이름
        "clarify_question": _NS,                       # missing이 있을 때 물을 질문 1개
        "profit_guarantee": {"type": "boolean"},       # 수익 보장을 요구하는가
        "tags": {"type": "array", "items": _S},        # 경로 결정에 쓰지 않는 분류용 태그
    },
    "required": ["goal", "sub_questions", "needs", "location", "crop", "period", "style", "missing",
                 "clarify_question", "profit_guarantee", "tags"],
    "additionalProperties": False,
}

PROFIT_NOTICE = "수익은 보장할 수 없습니다. 대신 지점 기후 지표와 시세 신호를 보여드립니다."

# 제주 본섬 대략 경계. shortcut: 바다·인근 섬 구분 못 함, 티켓 10이 바다 마스크로 이 함수를 대체한다.
JEJU_BBOX = (33.10, 33.60, 126.14, 126.98)  # lat_min, lat_max, lon_min, lon_max


def out_of_range(lat: float, lon: float) -> str | None:
    """좌표가 바다이거나 제주 본섬 밖이면 안내문, 안이면 None. DEM(티켓 10)을 쓰고, DEM 파일이 없으면 bbox로 폴백한다."""
    try:
        from jejuagent.geo import out_of_range_message
        return out_of_range_message(lat, lon)
    except FileNotFoundError:  # shortcut: DEM 없는 환경은 바다 구분 불가, DEM을 data/에 두면 해결
        a, b, c, d = JEJU_BBOX
        if a <= lat <= b and c <= lon <= d:
            return None
        return f"선택한 위치({lat:.3f}, {lon:.3f})가 제주 본섬 범위 밖입니다. 제주 본섬 안에서 위치를 다시 골라 주세요."


def output_format(plan: dict) -> str:
    needs = plan.get("needs") or {}
    if needs.get("point_analysis") or needs.get("spatial_comparison"):
        return "map"
    return "visual" if plan.get("style") == "easy" else "report"


def normalize(raw: dict, click: dict | None, prev_plan: dict | None) -> dict:
    """LLM 출력에 기본값을 채우고 좌표(클릭 > LLM > 이전 계획)를 확정한다."""
    p = dict(raw)
    p.setdefault("goal", "")
    p.setdefault("sub_questions", [])
    p["needs"] = {"point_analysis": False, "time_series": False, "spatial_comparison": False, **(p.get("needs") or {})}
    p["location"] = {"kind": "none", "text": None, "lat": None, "lon": None, **(p.get("location") or {})}
    for k in ("crop", "period", "clarify_question"):
        p.setdefault(k, None)
    p.setdefault("style", "unspecified")
    p["missing"] = list(p.get("missing") or [])
    p.setdefault("profit_guarantee", False)
    p.setdefault("tags", [])
    loc = p["location"]
    if click:
        loc.update(kind="point", lat=click["lat"], lon=click["lon"])
    elif loc.get("lat") is None and prev_plan:
        pl = prev_plan.get("location") or {}
        if pl.get("lat") is not None:
            loc.update(kind="point", lat=pl["lat"], lon=pl["lon"])
    return p


def apply_rules(plan: dict) -> dict:
    """코드 규칙: 위치 필수 판정과 산출물 형식. 점 분석인데 좌표가 없으면 '위치'가 빠진 것이다."""
    loc = plan["location"]
    has_point = loc.get("lat") is not None and loc.get("lon") is not None
    if plan["needs"]["point_analysis"] and not has_point and "위치" not in plan["missing"]:
        plan["missing"].append("위치")
    if has_point:
        plan["missing"] = [m for m in plan["missing"] if m != "위치"]
    plan["output_format"] = output_format(plan)
    return plan


def clarify_question(plan: dict) -> str:
    q = (plan.get("clarify_question") or "").strip()
    if q and "\n" not in q:
        return q
    m = plan["missing"][0]
    if m == "위치":
        return "어느 위치를 분석할까요? 지도에서 위치를 클릭한 뒤 다시 보내 주세요."
    return f"{m}을(를) 알려 주세요."
