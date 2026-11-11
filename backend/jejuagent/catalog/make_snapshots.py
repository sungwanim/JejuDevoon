"""거래 API 스냅샷 샘플(합성 데이터)을 만든다. 실행: python -m jejuagent.catalog.make_snapshots (backend/에서).
허브 명세(data/docs/schemas)의 응답 필드·문자열 숫자·0.00 결측 표기를 흉내 낸 가짜 값이며 실데이터가 아니다. 실데이터는 티켓 09."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[3] / "snapshots"
CULTIVARS = {"당근(일반)": 1800, "깐마늘": 6500, "월동무": 900, "양배추(일반)": 700, "중만생양파": 1100, "저장양파": 1000}
META = {"synthetic": True, "note": "합성 샘플이며 실데이터가 아님. 허브 API 명세의 필드와 표기 규칙만 따랐다. 실데이터는 티켓 09가 받는다.",
        "period": 7, "cultivars_total": 18, "cultivars_included": list(CULTIVARS)}


def build() -> tuple[list[dict], list[dict]]:
    rng = np.random.default_rng(20240101)
    days = pd.bdate_range("2024-01-01", "2024-03-29")
    daily, ma = [], []
    for cv, base in CULTIVARS.items():
        price = base * np.exp(np.cumsum(rng.normal(0, 0.03, len(days))))
        vol = rng.uniform(0.05, 1.5, len(days)).round(2)
        amt = price * vol / 1000            # 원/kg x 톤 -> 백만원
        s = pd.DataFrame({"p": price, "v": vol, "a": amt}, index=days)
        m = s.rolling(7, min_periods=1).mean().shift(1)
        for d in days:
            ds = d.strftime("%Y%m%d")
            daily.append({"baseDate": ds, "cultivar": cv, "averagePrice": f"{s.p[d]:.2f}",
                          "transactionVolume": f"{s.v[d]:.2f}", "transactionAmount": f"{s.a[d]:.2f}"})
            r = m.loc[d]
            f = lambda x: "0.00" if np.isnan(x) else f"{x:.2f}"   # 결측은 0.00으로 온다
            ma.append({"baseDate": ds, "cultivar": cv, "priceMovingAverage": f(r.p),
                       "volumeMovingAverage": f(r.v), "amountMovingAverage": f(r.a)})
    return daily, ma


def build_aws() -> pd.DataFrame:
    """[합성, 실데이터 아님] 지점 기후용 관측소 일자료(표준 스키마). 관측소 id SYN01~. 실데이터가 생기면 이 항목을 실제 AWS 변환 결과로 바꾼다."""
    from ..geo.climate import synthetic_aws
    df = synthetic_aws(n_stations=12, days=365).round({"elevation_m": 1, "tmean": 2, "tmin": 2, "tmax": 2, "precip": 1})
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df


def write_aws() -> None:
    meta = {"synthetic": True, "note": "합성 데이터이며 실제 관측소·관측값이 아니다. geo.climate.synthetic_aws(12, 365, seed 0)로 생성.",
            "schema": "station, lat, lon, elevation_m, date, tmean, tmin, tmax, precip"}
    (OUT / "synthetic_aws_daily.json").write_text(
        json.dumps({"meta": meta, "data": build_aws().to_dict("records")}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    daily, ma = build()
    for name, rows in (("jdh_agri_daily_trade", daily), ("jdh_agri_trade_moving_avg", ma)):
        (OUT / f"{name}.json").write_text(json.dumps({"meta": META, "data": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    write_aws()
