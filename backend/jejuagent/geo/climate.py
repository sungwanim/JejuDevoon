"""지점 기후 추정 (티켓 12). 부모 프로세스 쪽 얇은 층: DEM 고도를 미리 구해 모듈을 부른다.

계산은 modules_seed/site/site_climate.py 하나에 있다(격리 프로세스에서도 같은 코드). 방법·파라미터 근거는 docs/climate.md.
입력 표준 스키마와 한계 문구는 아래 AWS_SCHEMA / LIMITATIONS (렌더 단계가 쓰도록 데이터로 제공. 연결은 08 몫).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

from .dem import get_elevation, is_land, out_of_range_message

SEED_PATH = Path(__file__).resolve().parents[1] / "modules_seed" / "site" / "site_climate.py"
AWS_SCHEMA = {"station": "str(관측소 id)", "lat": "float(위도)", "lon": "float(경도)", "elevation_m": "float(관측소 고도, m)",
              "date": "날짜", "tmean": "일평균기온(℃)", "tmin": "일최저기온(℃)", "tmax": "일최고기온(℃, 현재 미사용)",
              "precip": "일강수량(mm)"}
_seed = None


def seed_module():
    global _seed
    if _seed is None:
        spec = importlib.util.spec_from_file_location("site_climate_seed", SEED_PATH)
        _seed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_seed)
    return _seed


def limitations() -> list[str]:
    m = seed_module()
    return list(m.LIMITATIONS)


def site_inputs(aws: pd.DataFrame, lat: float, lon: float) -> dict:
    """run()의 inputs. 지점 고도는 여기서(부모) DEM으로 구한다. 바다·격자 밖이면 ValueError(안내문)."""
    z = get_elevation(lat, lon)
    if z is None:
        raise ValueError(out_of_range_message(lat, lon) or "고도를 구할 수 없는 위치")
    return {"aws": aws, "site": pd.DataFrame([{"lat": lat, "lon": lon, "elevation_m": z}])}


def estimate_site(aws: pd.DataFrame, lat: float, lon: float, *, lapse_c_per_km: float = 6.5,
                  idw_power: float = 2.0, growing_months: str = "10,11,12,1,2,3") -> dict:
    """지점 기후 지표·교차검증 결과(dict, 모듈 출력과 같은 형식). """
    m = seed_module()
    params = {"lapse_c_per_km": lapse_c_per_km, "idw_power": idw_power, "growing_months": growing_months}
    inputs = site_inputs(aws, lat, lon)
    out = m.run(inputs, params)
    problems = m.check(out, inputs)
    if problems:
        raise ValueError("; ".join(problems))
    return out
