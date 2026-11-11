MANIFEST = {
    "id": "market-price-trend-volatility",
    "version": 1,
    "verified_by": "미검토 (검토 필요: 합성 스냅샷으로만 확인)",
    "title": "품목별 가격 추세와 변동성",
    "description": "품목(품종)별 일별 도매가격의 기간 변화율, 일평균 기울기(추세), 변동성(일수익률 표준편차, 변동계수)과 7일 이동평균을 계산한다",
    "tags": ["price", "trend", "volatility", "market"],
    "input_roles": {"trade": {"date": "date", "variety": "str", "price": "float"}},
    "params": {},
    "outputs": ["variety_trend_stats", "variety_daily_price"],
    "output_schema": [
        {"id": "variety_trend_stats", "kind": "table", "columns": [
            {"name": "variety", "dtype": "str", "unit": ""}, {"name": "n_days", "dtype": "int", "unit": "일"},
            {"name": "first_price", "dtype": "float", "unit": "원/kg"}, {"name": "last_price", "dtype": "float", "unit": "원/kg"},
            {"name": "change_pct", "dtype": "float", "unit": "%"}, {"name": "mean_price", "dtype": "float", "unit": "원/kg"},
            {"name": "slope_pct_per_day", "dtype": "float", "unit": "%/일"},
            {"name": "volatility_pct", "dtype": "float", "unit": "%"}, {"name": "cv_pct", "dtype": "float", "unit": "%"}]},
        {"id": "variety_daily_price", "kind": "series", "columns": [
            {"name": "variety", "dtype": "str", "unit": ""}, {"name": "date", "dtype": "date", "unit": ""},
            {"name": "price", "dtype": "float", "unit": "원/kg"}, {"name": "ma7", "dtype": "float", "unit": "원/kg"}]},
    ],
}


def run(inputs, params):
    import numpy as np
    import pandas as pd
    df = inputs["trade"][["date", "variety", "price"]].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna(subset=["date", "price"])
    if df.empty:
        raise DataProblem("유효한 가격 행이 없다")
    daily = df.groupby(["variety", "date"], as_index=False)["price"].mean().sort_values(["variety", "date"])
    daily["ma7"] = daily.groupby("variety")["price"].transform(lambda s: s.rolling(7, min_periods=1).mean())
    ret = daily.groupby("variety")["price"].pct_change()
    rows = []
    for v, d in daily.groupby("variety"):
        p = d["price"].to_numpy(dtype=float)
        r = ret.loc[d.index].dropna()
        mean = float(p.mean())
        slope = float(np.polyfit(np.arange(len(p)), p, 1)[0]) if len(p) >= 2 else 0.0
        rows.append({"variety": str(v), "n_days": int(len(p)), "first_price": float(p[0]), "last_price": float(p[-1]),
                     "change_pct": (float(p[-1]) / float(p[0]) - 1) * 100 if p[0] else 0.0, "mean_price": mean,
                     "slope_pct_per_day": slope / mean * 100 if mean else 0.0,
                     "volatility_pct": float(r.std() * 100) if len(r) >= 2 else 0.0,
                     "cv_pct": float(p.std() / mean * 100) if mean else 0.0})
    return {"variety_trend_stats": pd.DataFrame(rows),
            "variety_daily_price": daily.reset_index(drop=True)[["variety", "date", "price", "ma7"]]}


def check(outputs, inputs):
    s, d = outputs["variety_trend_stats"], outputs["variety_daily_price"]
    problems = []
    if s.empty or d.empty:
        problems.append("결과가 비었다")
    if (s["last_price"] <= 0).any() or (s["mean_price"] <= 0).any():
        problems.append("가격이 0 이하인 품목이 있다")
    if (s["volatility_pct"] < 0).any() or s.isna().any().any():
        problems.append("변동성이 음수이거나 결측이 있다")
    if set(s["variety"]) != set(d["variety"]):
        problems.append("통계와 일별 가격의 품목이 다르다")
    return problems
