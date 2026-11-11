"""카탈로그 요약 표: 'catalog_explorer' 같은 모듈의 입력. 카탈로그 항목(dict 목록) -> DataFrame."""
from __future__ import annotations

import pandas as pd


def catalog_summary_table(entries: list[dict]) -> pd.DataFrame:
    rows = [{"dataset_id": e["id"], "title": e["title"], "source": e.get("source", ""),
             "spatial_unit": e.get("spatial_unit", ""), "temporal_unit": e.get("temporal_unit", ""),
             "coverage_from": (e.get("coverage") or {}).get("from"), "coverage_to": (e.get("coverage") or {}).get("to"),
             "n_columns": len(e.get("columns", []))} for e in entries]
    df = pd.DataFrame(rows, columns=["dataset_id", "title", "source", "spatial_unit", "temporal_unit",
                                     "coverage_from", "coverage_to", "n_columns"])
    for c in ("coverage_from", "coverage_to"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["n_columns"] = df["n_columns"].astype(int)
    return df
