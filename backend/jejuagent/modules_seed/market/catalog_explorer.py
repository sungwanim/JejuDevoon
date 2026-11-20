MANIFEST = {
    "id": "market-catalog-explorer",
    "version": 1,
    "verified_by": "미검토 (검토 필요)",
    "title": "카탈로그 탐색",
    "description": "데이터셋 카탈로그 요약 표에서 어떤 데이터가 있는지, 기간 길이와 공간·시간 단위별 개수를 정리한다",
    "tags": ["catalog", "explore", "metadata"],
    "input_roles": {"catalog": {"dataset_id": "str", "title": "str", "spatial_unit": "str", "temporal_unit": "str",
                                "coverage_from": "date", "coverage_to": "date", "n_columns": "int"}},
    "params": {},
    "outputs": ["catalog_overview", "catalog_counts"],
    "output_schema": [
        {"id": "catalog_overview", "kind": "table", "columns": [
            {"name": "dataset_id", "dtype": "str", "unit": ""}, {"name": "title", "dtype": "str", "unit": ""},
            {"name": "temporal_unit", "dtype": "str", "unit": ""}, {"name": "spatial_unit", "dtype": "str", "unit": ""},
            {"name": "coverage_from", "dtype": "date", "unit": ""}, {"name": "coverage_to", "dtype": "date", "unit": ""},
            {"name": "span_days", "dtype": "int", "unit": "일"}, {"name": "n_columns", "dtype": "int", "unit": "개"}]},
        {"id": "catalog_counts", "kind": "metrics", "columns": []},
    ],
}


def run(inputs, params):
    import pandas as pd
    df = inputs["catalog"].copy()
    df["coverage_from"] = pd.to_datetime(df["coverage_from"], errors="coerce")
    df["coverage_to"] = pd.to_datetime(df["coverage_to"], errors="coerce")
    df["span_days"] = (df["coverage_to"] - df["coverage_from"]).dt.days.fillna(0).astype(int)
    cols = ["dataset_id", "title", "temporal_unit", "spatial_unit", "coverage_from", "coverage_to", "span_days", "n_columns"]
    overview = df.sort_values(["span_days", "dataset_id"], ascending=[False, True])[cols].reset_index(drop=True)
    overview["n_columns"] = overview["n_columns"].astype(int)
    counts = {"n_datasets": int(len(df)),
              "by_temporal_unit": {str(k): int(v) for k, v in df["temporal_unit"].value_counts().items()},
              "by_spatial_unit": {str(k): int(v) for k, v in df["spatial_unit"].value_counts().items()}}
    return {"catalog_overview": overview, "catalog_counts": counts}


def check(outputs, inputs):
    o, c = outputs["catalog_overview"], outputs["catalog_counts"]
    problems = []
    if o.empty:
        problems.append("카탈로그가 비었다")
    if c["n_datasets"] != len(inputs["catalog"]):
        problems.append("데이터셋 개수가 입력과 다르다")
    if (o["span_days"] < 0).any():
        problems.append("기간이 음수인 데이터셋이 있다")
    return problems
