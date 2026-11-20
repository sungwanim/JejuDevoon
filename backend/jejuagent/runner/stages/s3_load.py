"""③ 로드·Profile (티켓 03).

입력: state.selection ({"selected": [{"dataset_id": ...}]} 또는 id 문자열 목록), ctx.data
출력: state.data[id]=DataFrame, state.profiles[id]=Profile. 로드 실패는 state.load_failures에 적고 그 데이터만 빼고 진행
(partial 판정은 러너/후속 단계가 load_failures를 보고 한다).
지점 분석(점 좌표 + 관측소 데이터)이면 ③과 ④ 사이에서 부모 프로세스가 지점 고도(DEM)를 구해 입력 표 `site_point`를 state.data에 더한다. 폴백 안내는 state.extra["notices"].
"""
import pandas as pd

from ...catalog.profile import profile
from ...geo import get_elevation, out_of_range_message
from ... import thoughts
from ..selection import POINT_UNITS

SITE_ENTRY = {"id": "site_point", "title": "선택 지점 (DEM 고도)", "columns": [
    {"name": "lat", "meaning": "선택 지점 위도", "unit": "도", "role_hint": "lat"},
    {"name": "lon", "meaning": "선택 지점 경도", "unit": "도", "role_hint": "lon"},
    {"name": "elevation_m", "meaning": "선택 지점 DEM 고도(90m 격자, 부모 프로세스가 계산)", "unit": "m", "role_hint": "elevation"}]}


def _ids(selection) -> list[str]:
    sel = (selection or {}).get("selected", [])
    return [s if isinstance(s, str) else s["dataset_id"] for s in sel]


def _site_inputs(state, entries) -> None:
    plan = getattr(state, "plan", None) or {}
    loc = plan.get("location") or {}
    stations = [d for d in state.data if entries.get(d, {}).get("spatial_unit") in POINT_UNITS]
    if not ((plan.get("needs") or {}).get("point_analysis") and loc.get("lat") is not None and stations):
        return
    z = get_elevation(loc["lat"], loc["lon"])
    if z is None:  # 보통 ①이 먼저 걸러 낸다. 여기는 두 번째 안전장치
        state.finish("infeasible", out_of_range_message(loc["lat"], loc["lon"]) or "선택한 위치의 고도를 구할 수 없습니다.")
        state.needed_data = ["제주 본섬 안의 위치"]
        return
    df = pd.DataFrame([{"lat": loc["lat"], "lon": loc["lon"], "elevation_m": z}])
    state.data["site_point"], state.profiles["site_point"] = df, profile(df, "site_point", SITE_ENTRY)


def run(state, ctx):
    entries = {e["id"]: e for e in ctx.data.catalog()}
    for did in _ids(state.selection):
        try:
            df = ctx.data.load(did)
            state.profiles[did] = profile(df, did, entries.get(did))
            state.data[did] = df
            if df.attrs.get("data_mode") == "fallback":  # 09: 라이브 호출 실패 -> 스냅샷. 원인과 해결 방법을 사용자에게 보인다
                r = df.attrs.get("fallback_reason") or {}
                state.extra.setdefault("notices", []).append(
                    f"'{did}'은(는) 라이브 데이터를 받지 못해 저장된 스냅샷을 썼습니다. 원인: {r.get('cause', '알 수 없음')}. 해결: {r.get('fix', '')}")
        except Exception as e:  # 한 데이터의 실패가 전체를 막지 않는다
            state.load_failures.append({"dataset_id": did, "error": f"{type(e).__name__}: {e}"})
            ctx.trace.add("decision", stage="s3_load", dataset_id=did, load_failed=str(e))
    _site_inputs(state, entries)
    titles = {k: v.get("title") or k for k, v in entries.items()}
    for line in thoughts.after_load(state.data, titles, state.load_failures):
        thoughts.say(ctx, "s3_load", line)
    return state
