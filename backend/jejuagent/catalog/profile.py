"""Profile 생성 (DESIGN.md §2 ③ 형식)."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd


def _py(v):
    """JSON 직렬화 가능한 파이썬 값으로."""
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, np.generic):
        return v.item()
    return v


def _dtype(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_integer_dtype(s):
        return "int"
    if pd.api.types.is_float_dtype(s):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    return "str"


def _samples(s: pd.Series, k: int = 5) -> list:
    u = s.dropna().unique()
    idx = np.unique(np.linspace(0, len(u) - 1, min(k, len(u))).round().astype(int)) if len(u) else []
    return [_py(u[i]) for i in idx]


def profile(df: pd.DataFrame, dataset_id: str = "", entry: dict | None = None) -> dict:
    """행 수, 인코딩, 컬럼별 타입·결측률(null_pct, 0~100)·최소·최대·고유값 수·샘플 3~5개, 카탈로그의 의미·단위, 데이터 버전 해시."""
    meta = {c["name"]: c for c in (entry or {}).get("columns", [])}
    h = hashlib.sha256(pd.util.hash_pandas_object(df, index=False).values.tobytes())
    h.update("|".join(map(str, df.columns)).encode("utf-8"))
    cols = []
    for name in df.columns:
        s, m = df[name], meta.get(name, {})
        d = _dtype(s)
        ordered = d in ("int", "float", "date")
        cols.append({
            "name": name, "meaning": m.get("meaning", ""), "unit": m.get("unit", ""), "role_hint": m.get("role_hint", ""),
            "dtype": d, "null_pct": round(float(s.isna().mean() * 100), 2) if len(s) else 0.0,
            "min": _py(s.min()) if ordered and s.notna().any() else None,
            "max": _py(s.max()) if ordered and s.notna().any() else None,
            "n_unique": int(s.nunique()), "samples": _samples(s),
        })
    return {"dataset_id": dataset_id, "version_hash": h.hexdigest()[:16], "n_rows": int(len(df)),
            "encoding": df.attrs.get("encoding", ""), "columns": cols}
