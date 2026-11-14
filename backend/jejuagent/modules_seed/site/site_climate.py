"""지점 기후 추정 + 교차검증 (티켓 12). verified 모듈 소스: 코드 계약(MANIFEST, run, check)을 지킨다.

단일 소스: 순수 계산(numpy/pandas만)이 전부 이 파일에 있다. jejuagent.geo.climate가 이 파일을
경로로 불러 쓴다 (격리 프로세스는 jejuagent를 import할 수 없으므로 거꾸로 이 파일이 자립한다).

입력 표준 스키마(실제 AWS API·CSV를 추측해 만든 변환기는 없다. 사용자가 이 스키마로 변환한다):
  aws  (관측소 x 일): station(str) lat lon elevation_m(m) date tmean tmin [tmax] precip(mm)  (기온 ℃)
  site (1행): lat lon elevation_m   <- 부모 프로세스가 get_elevation으로 미리 계산해 넘긴다 (DEM은 여기서 못 읽음)
방법: 관측소 값에 +감률*고도로 해면 환산 -> IDW(거리^-p)로 보간 -> 지점 고도에서 -감률*고도로 되돌림.
"""
try:
    DataProblem
except NameError:  # 격리 프로세스 밖(부모)에서 불러 쓸 때
    class DataProblem(Exception):
        pass
import numpy as np
import pandas as pd

MANIFEST = {
    "title": "지점 기후 추정",
    "description": "AWS 관측값을 고도 보정 IDW로 지점에 보간해 기온 지표(연평균·극최저·생육기간 평균)를 내고, 관측소 하나씩 빼는 교차검증 오차를 낸다.",
    "tags": ["climate", "interpolation", "aws", "elevation"],
    "input_roles": {
        "aws": {"station": "str", "lat": "float", "lon": "float", "elevation_m": "float", "date": "date",
                "tmean": "float", "tmin": "float", "precip": "float"},
        "site": {"lat": "float", "lon": "float", "elevation_m": "float"},
    },
    "params": {"lapse_c_per_km": "float", "idw_power": "float", "growing_months": "str", "synthetic": "bool"},
    "outputs": ["site_markers", "site_indicators", "cross_validation", "limitations"],
    "output_schema": [
        {"id": "site_markers", "kind": "geo", "columns": [
            {"name": "name", "dtype": "str", "unit": ""}, {"name": "role", "dtype": "str", "unit": ""},
            {"name": "lat", "dtype": "float", "unit": "도"}, {"name": "lon", "dtype": "float", "unit": "도"},
            {"name": "elevation_m", "dtype": "float", "unit": "m"}, {"name": "annual_mean_c", "dtype": "float", "unit": "℃"}]},
        {"id": "site_indicators", "kind": "metrics", "columns": []},
        {"id": "cross_validation", "kind": "table", "columns": [
            {"name": "method", "dtype": "str", "unit": ""}, {"name": "mae_daily_c", "dtype": "float", "unit": "℃"}]},
        {"id": "limitations", "kind": "table", "columns": [{"name": "text", "dtype": "str", "unit": ""}]},
    ],
}

LAPSE_DEFAULT = 6.5          # ℃/km. Ryu 외 2024가 제주 기본값으로 쓴 값. 실데이터로 검증하지 못함
IDW_POWER_DEFAULT = 2.0
GROWING_MONTHS_DEFAULT = "10,11,12,1,2,3"   # 가정(월동 채소 중심). 기준표의 작형은 텍스트라 코드가 읽지 않는다
MIN_DIST_KM = 0.1            # 관측소 바로 위 지점의 0 나눗셈 방지

LIMITATIONS = [
    "기온은 AWS 관측소 값을 기온감률로 고도 보정한 뒤 IDW로 보간한 추정값이며 실측이 아니다.",
    "고도는 90m DEM 한 칸의 값이다. 칸 안의 실제 지형과 필지 고도는 다를 수 있다.",
    "경사·사면 방향·일사량·바람·냉기 정체·해안 효과는 반영하지 않는다.",
    "관측소 수와 배치가 한정적이다. 관측소에서 멀거나 관측소가 드문 고도대(특히 한라산 고지대)는 오차가 커질 수 있다.",
    "강수량은 고도 보정 없이 IDW로 보간했다. 지형성 강수 효과는 반영하지 않는다.",
    "극최저기온·-5℃ 이하 일수·0℃ 이하 일수는 참고 지표다. 동해·저온 한계온도로 합격/불합격을 판정하지 않는다(신뢰할 만한 한계온도 자료가 없다).",
    "재배 적합도는 공공데이터셋 근거가 없어 판정하지 않는다.",
]
SYNTHETIC_NOTE = "합성 데이터로 계산한 결과다. 오차 수치를 실제 성능으로 해석하면 안 된다."
REFERENCE_NOTE = "참고 지표(판정 아님)"


def _km(lat0, lon0, lat, lon):
    return np.hypot((np.asarray(lon) - lon0) * np.cos(np.radians(lat0)) * 111.32, (np.asarray(lat) - lat0) * 110.57)


def _interp(vals, lats, lons, zs, lat, lon, z, lapse, power):
    """vals (일 x 관측소, 결측 NaN) -> (일,) 지점 추정. lapse는 ℃/km (0이면 고도 보정 없음)."""
    g = lapse / 1000.0
    sea = vals + g * zs
    w = 1.0 / np.maximum(_km(lat, lon, lats, lons), MIN_DIST_KM) ** power
    m = ~np.isnan(sea)
    den = (m * w).sum(1)
    est = np.where(m, sea * w, 0.0).sum(1) / np.where(den > 0, den, np.nan)
    return est - g * z


def _nearest(vals, lats, lons, lat, lon):
    d = np.where(np.isnan(vals), np.inf, _km(lat, lon, lats, lons))
    j = d.argmin(1)
    out = vals[np.arange(len(vals)), j]
    return np.where(np.isinf(d.min(1)), np.nan, out)


def fit_lapse(period_means, zs):
    """관측소 기간 평균 기온을 고도에 회귀한 기온감률(℃/km). 고도 범위가 100m 미만이면 None."""
    ok = ~np.isnan(period_means)
    if ok.sum() < 3 or np.ptp(zs[ok]) < 100:
        return None
    return float(-np.polyfit(zs[ok], period_means[ok], 1)[0] * 1000)


def prepare(aws):
    """표준 스키마 DataFrame -> 관측소 표와 변수별 (일 x 관측소) 배열."""
    need = ["station", "lat", "lon", "elevation_m", "date", "tmean", "tmin", "precip"]
    miss = [c for c in need if c not in aws.columns]
    if miss:
        raise DataProblem(f"표준 스키마에 없는 컬럼: {miss}")
    df = aws.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["station"] = df["station"].astype(str)
    st = df.groupby("station")[["lat", "lon", "elevation_m"]].first().dropna()
    if len(st) < 3:
        raise DataProblem(f"좌표·고도가 있는 관측소가 3개 미만이다({len(st)}개)")
    grid = {v: df.pivot_table(index="date", columns="station", values=v, aggfunc="mean").reindex(columns=st.index)
            for v in ("tmean", "tmin", "precip")}
    dates = grid["tmean"].index
    return st, dates, {v: g.to_numpy(float) for v, g in grid.items()}


def _nanmean(a):
    a = np.asarray(a, float)
    return float(np.nanmean(a)) if np.isfinite(a).any() else float("nan")


def _mae(est, obs):
    return _nanmean(np.abs(est - obs))


def cross_validate(st, arrays, lapse, power):
    """관측소를 하나씩 빼고 그 관측소의 일 기온(tmean, tmin)을 추정해 오차를 낸다. 방법별로 관측소 평균."""
    lats, lons, zs = (st[c].to_numpy(float) for c in ("lat", "lon", "elevation_m"))
    acc = {}
    for i in range(len(st)):
        keep = np.arange(len(st)) != i
        for var in ("tmean", "tmin"):
            v = arrays[var]
            obs = v[:, i]
            args = (lats[keep], lons[keep], zs[keep], lats[i], lons[i], zs[i])
            fit = fit_lapse(np.nanmean(v[:, keep], 0), zs[keep])
            ests = {
                "idw_lapse_fixed": (_interp(v[:, keep], *args, lapse, power), lapse),
                "idw_lapse_fitted": (None if fit is None else _interp(v[:, keep], *args, fit, power), fit),
                "idw_no_elevation": (_interp(v[:, keep], *args, 0.0, power), 0.0),
                "nearest_station": (_nearest(v[:, keep], lats[keep], lons[keep], lats[i], lons[i]), None),
            }
            for name, (e, lp) in ests.items():
                if e is None:
                    continue
                both = ~np.isnan(e) & ~np.isnan(obs)
                a = acc.setdefault((name, var), {"daily": [], "mean": [], "lapse": []})
                a["daily"].append(_mae(e, obs))
                a["mean"].append(abs(e[both].mean() - obs[both].mean()) if both.any() else np.nan)
                if lp is not None:
                    a["lapse"].append(lp)
    rows = [{"method": m, "variable": var, "mae_daily_c": _nanmean(a["daily"]), "mae_period_mean_c": _nanmean(a["mean"]),
             "lapse_c_per_km": _nanmean(a["lapse"]) if a["lapse"] else np.nan, "n_stations": len(st)}
            for (m, var), a in acc.items()]
    return pd.DataFrame(rows, columns=["method", "variable", "mae_daily_c", "mae_period_mean_c", "lapse_c_per_km", "n_stations"])


def site_indicators(st, dates, arrays, lat, lon, z, lapse, power, growing_months):
    """지점의 파생 지표(전부 참고 정보). 추정은 일 단위로 한 뒤 집계한다."""
    lats, lons, zs = (st[c].to_numpy(float) for c in ("lat", "lon", "elevation_m"))
    tmean = _interp(arrays["tmean"], lats, lons, zs, lat, lon, z, lapse, power)
    tmin = _interp(arrays["tmin"], lats, lons, zs, lat, lon, z, lapse, power)
    precip = _interp(arrays["precip"], lats, lons, zs, lat, lon, z, 0.0, power)
    ok = ~np.isnan(tmean)
    years = ok.sum() / 365.25
    if years <= 0:
        raise DataProblem("지점 기온을 추정할 수 있는 날짜가 없다")
    months = pd.DatetimeIndex(dates).month.to_numpy()
    grow = ok & np.isin(months, growing_months)
    tm_ok = ~np.isnan(tmin)
    return {
        "annual_mean_c": float(np.nanmean(tmean)),
        "extreme_min_c": float(np.nanmin(tmin)) if tm_ok.any() else float("nan"),
        "days_le_minus5_per_year": float((tmin[tm_ok] <= -5).sum() / years),
        "days_le_0_per_year": float((tmin[tm_ok] <= 0).sum() / years),
        "growing_mean_c": float(tmean[grow].mean()) if grow.any() else float("nan"),
        "precip_mm_per_year": float(np.nansum(precip) / years) if np.isfinite(precip).any() else float("nan"),
        "n_days": int(ok.sum()), "n_years": round(float(years), 2),
        "growing_months": ",".join(str(int(m)) for m in growing_months),
        "lapse_c_per_km": float(lapse), "idw_power": float(power),
        "reference_note": REFERENCE_NOTE,
    }



def run(inputs, params):
    lapse = float(params.get("lapse_c_per_km", LAPSE_DEFAULT))
    power = float(params.get("idw_power", IDW_POWER_DEFAULT))
    months = [int(m) for m in str(params.get("growing_months", GROWING_MONTHS_DEFAULT)).split(",") if m.strip()]
    site = inputs["site"]
    if len(site) < 1:
        raise DataProblem("지점 입력이 비어 있다")
    lat, lon, z = (float(site[c].iloc[0]) for c in ("lat", "lon", "elevation_m"))
    st, dates, arrays = prepare(inputs["aws"])
    ind = site_indicators(st, dates, arrays, lat, lon, z, lapse, power, months)
    cv = cross_validate(st, arrays, lapse, power)
    syn = bool(params.get("synthetic", False))
    cv["note"] = SYNTHETIC_NOTE if syn else ""
    pick = lambda m: float(cv[(cv.method == m) & (cv.variable == "tmean")].mae_daily_c.iloc[0])
    ind["cv_mae_daily_tmean_c"] = pick("idw_lapse_fixed")
    ind["cv_mae_daily_tmean_nearest_c"] = pick("nearest_station")
    ind["synthetic"] = syn
    ind["data_note"] = SYNTHETIC_NOTE if syn else ""
    ind["elevation_m"] = z
    markers = pd.concat([
        pd.DataFrame([{"name": "선택 지점(추정)", "role": "site", "lat": lat, "lon": lon, "elevation_m": z,
                       "annual_mean_c": ind["annual_mean_c"]}]),
        pd.DataFrame({"name": st.index, "role": "station", "lat": st.lat.to_numpy(), "lon": st.lon.to_numpy(),
                      "elevation_m": st.elevation_m.to_numpy(), "annual_mean_c": np.nanmean(arrays["tmean"], 0)}),
    ], ignore_index=True)
    lim = list(LIMITATIONS) + ([SYNTHETIC_NOTE] if syn else []) + [f"관측소 {len(st)}개, 관측 {ind['n_years']}년분으로 추정했다."]
    return {
        "site_markers": markers,
        "site_indicators": ind,
        "cross_validation": cv,
        "limitations": pd.DataFrame({"text": lim}),
    }


def check(outputs, inputs):
    p = []
    ind = outputs["site_indicators"]
    if not np.isfinite(ind["annual_mean_c"]) or not -30 < ind["annual_mean_c"] < 40:
        p.append(f"연평균기온 {ind['annual_mean_c']}℃가 비었거나 상식 범위를 벗어났다")
    if outputs["limitations"].empty:
        p.append("한계 문구가 없다")
    return p
