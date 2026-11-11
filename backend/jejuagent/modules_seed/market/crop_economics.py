MANIFEST = {
    "id": "market-crop-economics",
    "version": 1,
    "verified_by": "미검토 (검토 필요: 허브 재배현황 CSV 168행과 20-21 월동무 수치로 확인)",
    "title": "작목별 면적당 조수입과 재배면적 추세",
    "description": "채소 재배현황(연산별 면적·생산량·조수입)으로 작목별 면적당 조수입, 수량, 단가, 재배면적 증감과 작목 간 순위를 노지/시설로 나눠 계산한다. 도 전체 단위, 조수입 기준(비용·순이익 아님)",
    "tags": ["crop", "revenue", "area", "trend", "economics", "market", "면적당 조수입", "재배면적"],
    "input_roles": {"cultivation": {"season": "str", "crop_group": "str", "crop": "str", "area": "float",
                                    "production": "float", "revenue": "float"}},
    "params": {},
    "outputs": ["crop_metrics", "crop_ranking", "crop_area_trend", "limitations"],
    "output_schema": [
        {"id": "crop_metrics", "kind": "table", "columns": [
            {"name": "season", "dtype": "str", "unit": ""}, {"name": "crop_group", "dtype": "str", "unit": ""},
            {"name": "crop", "dtype": "str", "unit": ""}, {"name": "area_ha", "dtype": "float", "unit": "ha"},
            {"name": "production_t", "dtype": "float", "unit": "톤"}, {"name": "revenue_mw", "dtype": "float", "unit": "백만원"},
            {"name": "revenue_per_ha_mw", "dtype": "float", "unit": "백만원/ha"},
            {"name": "yield_t_per_ha", "dtype": "float", "unit": "톤/ha"},
            {"name": "unit_price_won_per_kg", "dtype": "float", "unit": "원/kg"},
            {"name": "is_aggregate", "dtype": "bool", "unit": ""}]},
        {"id": "crop_ranking", "kind": "table", "columns": [
            {"name": "crop_group", "dtype": "str", "unit": ""}, {"name": "rank", "dtype": "int", "unit": "위"},
            {"name": "crop", "dtype": "str", "unit": ""}, {"name": "season", "dtype": "str", "unit": ""},
            {"name": "area_ha", "dtype": "float", "unit": "ha"},
            {"name": "revenue_per_ha_mw", "dtype": "float", "unit": "백만원/ha"},
            {"name": "yield_t_per_ha", "dtype": "float", "unit": "톤/ha"},
            {"name": "unit_price_won_per_kg", "dtype": "float", "unit": "원/kg"},
            {"name": "area_change_pct_vs_prev", "dtype": "float", "unit": "%"},
            {"name": "area_change_pct_vs_first", "dtype": "float", "unit": "%"},
            {"name": "n_seasons", "dtype": "int", "unit": "개"}]},
        {"id": "crop_area_trend", "kind": "series", "columns": [
            {"name": "crop_group", "dtype": "str", "unit": ""}, {"name": "crop", "dtype": "str", "unit": ""},
            {"name": "season", "dtype": "str", "unit": ""}, {"name": "area_ha", "dtype": "float", "unit": "ha"},
            {"name": "area_change_pct", "dtype": "float", "unit": "%"}]},
        {"id": "limitations", "kind": "table", "columns": [{"name": "text", "dtype": "str", "unit": ""}]},
    ],
}

# 단위 변환: 조수입(백만원) x 1,000,000 = 원, 생산량(톤) x 1,000 = kg. 단가 = 원 / kg.
WON_PER_MW = 1_000_000
KG_PER_TON = 1_000
# 반올림: 계산은 전체 정밀도로 하고 출력에서만 소수 둘째 자리(면적·생산량·조수입 원값은 그대로).
DECIMALS = 2

LIMITATIONS = [
    "도 전체 단위 자료라 지점·읍면동별 차이는 설명하지 못한다.",
    "조수입(판매 총수입) 기준이며 비용 자료가 없어 순이익이 아니다.",
    "자료 기준일은 2021-08-09이고 최신 연산은 20-21이다. 현재 상황과 다를 수 있다.",
    "과거 조수입·면적 추세는 수익을 보장하지 않는다.",
    "'기타(…)'로 묶인 항목은 여러 작목의 합이라 순위 비교에서 제외했다.",
]


def run(inputs, params):
    import pandas as pd
    src = inputs["cultivation"]
    df = pd.DataFrame({"season": src["season"].astype(str).str.strip(), "crop_group": src["crop_group"].astype(str).str.strip(),
                       "crop": src["crop"].astype(str).str.strip()})
    for k, c in (("area_ha", "area"), ("production_t", "production"), ("revenue_mw", "revenue")):
        df[k] = pd.to_numeric(src[c], errors="coerce")
    df = df.dropna(subset=["area_ha", "production_t", "revenue_mw"])
    df = df[(df["area_ha"] > 0) & (df["production_t"] > 0)]
    if df.empty:
        raise DataProblem("면적·생산량이 0보다 큰 유효한 행이 없다")
    df["revenue_per_ha_mw"] = df["revenue_mw"] / df["area_ha"]
    df["yield_t_per_ha"] = df["production_t"] / df["area_ha"]
    df["unit_price_won_per_kg"] = df["revenue_mw"] * WON_PER_MW / (df["production_t"] * KG_PER_TON)
    df["is_aggregate"] = df["crop"].str.startswith("기타")
    df = df.sort_values(["crop_group", "crop", "season"]).reset_index(drop=True)
    df["area_change_pct"] = df.groupby(["crop_group", "crop"])["area_ha"].pct_change() * 100

    latest = df["season"].max()
    base = df[~df["is_aggregate"]]
    g = base.groupby(["crop_group", "crop"])
    cur = base.assign(area_change_pct_vs_first=(base["area_ha"] / g["area_ha"].transform("first") - 1) * 100,
                      n_seasons=g["season"].transform("count"))
    cur = cur[cur["season"] == latest].rename(columns={"area_change_pct": "area_change_pct_vs_prev"})
    cur = cur.sort_values(["crop_group", "revenue_per_ha_mw"], ascending=[True, False])
    cur["rank"] = cur.groupby("crop_group").cumcount() + 1
    rank_cols = ["crop_group", "rank", "crop", "season", "area_ha", "revenue_per_ha_mw", "yield_t_per_ha", "unit_price_won_per_kg",
                 "area_change_pct_vs_prev", "area_change_pct_vs_first", "n_seasons"]
    ranking = cur[rank_cols].reset_index(drop=True)
    fl = ranking.select_dtypes("float").columns
    ranking[fl] = ranking[fl].round(DECIMALS)

    metrics = df.drop(columns=["area_change_pct"])
    mc = ["revenue_per_ha_mw", "yield_t_per_ha", "unit_price_won_per_kg"]
    metrics[mc] = metrics[mc].round(DECIMALS)
    trend = base[["crop_group", "crop", "season", "area_ha", "area_change_pct"]].copy()
    trend["area_change_pct"] = trend["area_change_pct"].round(DECIMALS)
    lim = LIMITATIONS + [f"최신 연산 {latest} 기준 순위이며 연산 {df['season'].nunique()}개({df['season'].min()}~{latest})를 사용했다."]
    return {"crop_metrics": metrics, "crop_ranking": ranking, "crop_area_trend": trend.reset_index(drop=True),
            "limitations": pd.DataFrame({"text": lim})}


def check(outputs, inputs):
    m, r = outputs["crop_metrics"], outputs["crop_ranking"]
    problems = []
    if m.empty or r.empty or outputs["crop_area_trend"].empty:
        return ["결과가 비었다"]
    if (m[["revenue_per_ha_mw", "yield_t_per_ha", "unit_price_won_per_kg"]] <= 0).any().any():
        problems.append("면적당 조수입·수량·단가가 0 이하인 행이 있다")
    if r["crop"].str.startswith("기타").any():
        problems.append("'기타(…)' 묶음이 순위에 들어 있다")
    for g, d in r.groupby("crop_group"):
        if sorted(d["rank"]) != list(range(1, len(d) + 1)) or not d["revenue_per_ha_mw"].is_monotonic_decreasing:
            problems.append(f"{g} 순위가 면적당 조수입 내림차순이 아니다")
    # 단위 변환 검산: 첫 행의 단가를 원 단위로 다시 계산
    x = m.iloc[0]
    if abs(x["unit_price_won_per_kg"] - x["revenue_mw"] * 1_000_000 / (x["production_t"] * 1_000)) > 0.01:
        problems.append("단가 단위 변환이 맞지 않는다")
    return problems
