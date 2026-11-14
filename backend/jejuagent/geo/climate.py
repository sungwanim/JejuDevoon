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


def limitations(synthetic: bool = False) -> list[str]:
    m = seed_module()
    return list(m.LIMITATIONS) + ([m.SYNTHETIC_NOTE] if synthetic else [])


def site_inputs(aws: pd.DataFrame, lat: float, lon: float) -> dict:
    """run()의 inputs. 지점 고도는 여기서(부모) DEM으로 구한다. 바다·격자 밖이면 ValueError(안내문)."""
    z = get_elevation(lat, lon)
    if z is None:
        raise ValueError(out_of_range_message(lat, lon) or "고도를 구할 수 없는 위치")
    return {"aws": aws, "site": pd.DataFrame([{"lat": lat, "lon": lon, "elevation_m": z}])}


def estimate_site(aws: pd.DataFrame, lat: float, lon: float, *, lapse_c_per_km: float = 6.5,
                  idw_power: float = 2.0, growing_months: str = "10,11,12,1,2,3", synthetic: bool | None = None) -> dict:
    """지점 기후 지표·교차검증 결과(dict, 모듈 출력과 같은 형식). synthetic=None이면 aws.attrs['synthetic']를 따른다."""
    syn = bool(aws.attrs.get("synthetic")) if synthetic is None else synthetic
    m = seed_module()
    params = {"lapse_c_per_km": lapse_c_per_km, "idw_power": idw_power, "growing_months": growing_months, "synthetic": syn}
    inputs = site_inputs(aws, lat, lon)
    out = m.run(inputs, params)
    problems = m.check(out, inputs)
    if problems:
        raise ValueError("; ".join(problems))
    return out


def synthetic_aws(n_stations: int = 24, days: int = 365, seed: int = 0, start: str = "2023-01-01") -> pd.DataFrame:
    """[합성, 실데이터 아님] 표준 스키마 AWS 일자료. 관측소는 DEM 육지 칸(일부는 한라산 부근)에 무작위로 놓는다.
    기온 = 계절 + 고도 효과(-6.5℃/km) + 남북 완만한 차이 + 잡음. 관측소 위치·값 모두 지어낸 것이다."""
    rng = np.random.default_rng(seed)
    pts = []
    while len(pts) < n_stations:
        near = len(pts) % 3 == 0
        lat, lon = (rng.normal(33.36, 0.05), rng.normal(126.53, 0.07)) if near else (rng.uniform(33.2, 33.55), rng.uniform(126.2, 126.95))
        z = get_elevation(lat, lon) if is_land(lat, lon) else None
        if z is not None:
            pts.append((f"SYN{len(pts) + 1:02d}", round(lat, 4), round(lon, 4), round(z, 1)))
    dates = pd.date_range(start, periods=days)
    doy = dates.day_of_year.to_numpy()
    season = 15.5 + 11 * np.sin(2 * np.pi * (doy - 110) / 365.25)
    common = rng.normal(0, 2.0, days)
    rows = []
    for sid, lat, lon, z in pts:
        t = season + common - 0.0065 * z - 1.0 * (lat - 33.4) / 0.15 + rng.normal(0, 0.3) + rng.normal(0, 0.4, days)
        rain = np.where(rng.random(days) < 0.25, rng.exponential(12, days) * (1 + z / 1500), 0.0)
        rows.append(pd.DataFrame({"station": sid, "lat": lat, "lon": lon, "elevation_m": z, "date": dates,
                                  "tmean": t, "tmin": t - 4 + rng.normal(0, 0.8, days), "tmax": t + 4 + rng.normal(0, 0.8, days),
                                  "precip": rain.round(1)}))
    df = pd.concat(rows, ignore_index=True)
    df.attrs["synthetic"] = True
    return df
