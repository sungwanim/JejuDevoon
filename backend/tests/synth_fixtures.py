"""[테스트 전용] 가짜 관측·시세 데이터 생성기. 제품 코드와 제출 데이터에는 쓰지 않는다 (앱은 실데이터만 쓴다).
가짜 LLM 시나리오 테스트(e2e, 평가 드라이런)가 키·네트워크 없이 돌도록 임시 폴더에 스냅샷을 만들 때만 쓴다."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from jejuagent.geo.dem import get_elevation, is_land


def fake_weather(n_stations: int = 24, days: int = 365, seed: int = 0, start: str = "2023-01-01") -> pd.DataFrame:
    """[테스트용 가짜] 표준 스키마 AWS 일자료. 관측소는 DEM 육지 칸(일부는 한라산 부근)에 무작위로 놓는다.
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
    return df


CULTIVARS = {"당근(일반)": 1800, "깐마늘": 6500, "월동무": 900, "양배추(일반)": 700, "중만생양파": 1100, "저장양파": 1000}


def fake_price() -> tuple[list[dict], list[dict]]:
    """허브 API 응답 모양(문자열 숫자, 이동평균 결측은 0.00)을 흉내 낸 테스트용 거래 통계·이동평균 행."""
    rng = np.random.default_rng(20240101)
    days = pd.bdate_range("2024-01-01", "2024-03-29")
    daily, ma = [], []
    for cv, base in CULTIVARS.items():
        price = base * np.exp(np.cumsum(rng.normal(0, 0.03, len(days))))
        vol = rng.uniform(0.05, 1.5, len(days)).round(2)
        s = pd.DataFrame({"p": price, "v": vol, "a": price * vol / 1000}, index=days)
        m = s.rolling(7, min_periods=1).mean().shift(1)
        for d in days:
            ds = d.strftime("%Y%m%d")
            daily.append({"baseDate": ds, "cultivar": cv, "averagePrice": f"{s.p[d]:.2f}",
                          "transactionVolume": f"{s.v[d]:.2f}", "transactionAmount": f"{s.a[d]:.2f}"})
            r = m.loc[d]
            f = lambda x: "0.00" if np.isnan(x) else f"{x:.2f}"
            ma.append({"baseDate": ds, "cultivar": cv, "priceMovingAverage": f(r.p), "volumeMovingAverage": f(r.v),
                       "amountMovingAverage": f(r.a)})
    return daily, ma


def write_test_snapshots(snapshots_dir: Path) -> None:
    """snapshots_dir/live/ 에 실데이터 스냅샷과 같은 이름·형식의 테스트용 파일 3개를 쓴다."""
    live = Path(snapshots_dir) / "live"
    live.mkdir(parents=True, exist_ok=True)
    daily, ma = fake_price()
    w = fake_weather(n_stations=12, days=365).round({"elevation_m": 1, "tmean": 2, "tmin": 2, "tmax": 2, "precip": 1})
    w["date"] = w["date"].dt.strftime("%Y-%m-%d")
    w.insert(1, "name", w["station"])
    for name, rows in (("jdh_agri_daily_trade", daily), ("jdh_agri_trade_moving_avg", ma), ("jeju_weather_daily", w.to_dict("records"))):
        (live / f"{name}.json").write_text(json.dumps({"meta": {"test_fixture": True}, "data": rows}, ensure_ascii=False,
                                                       separators=(",", ":")), encoding="utf-8")
