"""Profile(DESIGN.md §2 ③ 형식)로 가짜 데이터프레임을 만든다.

입력 Profile 가정: {"n_rows": int, "columns": [{"name", "dtype", "null_pct"(0~100 퍼센트), "min", "max",
"n_unique", "samples": [...]}]}. dtype은 float|int|str|date|bool (별칭 허용).
반영하는 것: 컬럼 이름·타입, 결측률, [min, max] 범위(양끝 값 포함), 샘플 값(모두 포함),
문자열은 샘플 값 안에서만 선택. 반영하지 않는 것: 컬럼 간 관계, 분포 모양, 정렬(날짜 제외).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_KIND = {"float": "float", "double": "float", "number": "float", "int": "int", "integer": "int",
         "str": "str", "string": "str", "object": "str", "category": "str",
         "date": "date", "datetime": "date", "timestamp": "date", "bool": "bool", "boolean": "bool"}


def make_mock_dataframe(profile: dict, n_rows: int | None = None, seed: int = 0, max_rows: int = 200) -> pd.DataFrame:
    n = int(n_rows if n_rows is not None else min(profile.get("n_rows", max_rows), max_rows))
    rng = np.random.default_rng(seed)
    cols = {}
    for c in profile["columns"]:
        cols[c["name"]] = _make_column(c, n, rng)
    return pd.DataFrame(cols, index=pd.RangeIndex(n))


def mock_inputs(profiles: dict[str, dict], **kw) -> dict[str, pd.DataFrame]:
    """입력 이름 -> Profile 사전을 입력 이름 -> 가짜 데이터프레임 사전으로."""
    return {name: make_mock_dataframe(p, **kw) for name, p in profiles.items()}


def _make_column(c: dict, n: int, rng) -> pd.Series:
    kind = _KIND.get(str(c.get("dtype", "str")).lower(), "str")
    samples = [s for s in (c.get("samples") or []) if s is not None]
    lo, hi = c.get("min"), c.get("max")
    if n == 0:
        return pd.Series([], dtype={"float": "float64", "int": "Int64", "str": "str", "date": "datetime64[ns]", "bool": "boolean"}[kind])

    if kind == "str":
        pool = [str(s) for s in samples] or [f"v{i}" for i in range(max(1, min(int(c.get("n_unique") or 3), 10)))]
        values = list(rng.choice(pool, size=n))
        seeds = pool
    elif kind == "bool":
        values = list(rng.random(n) < 0.5)
        seeds = [bool(s) for s in samples]
    elif kind == "date":
        ts = [pd.Timestamp(x) for x in (samples + [lo, hi]) if x is not None]
        a = pd.Timestamp(lo) if lo is not None else (min(ts) if ts else pd.Timestamp("2020-01-01"))
        b = pd.Timestamp(hi) if hi is not None else (max(ts) if ts else a + pd.Timedelta(days=365))
        span = max((b - a).days, 0)
        values = [a + pd.Timedelta(days=int(d)) for d in rng.integers(0, span + 1, size=n)]
        seeds = [pd.Timestamp(s) for s in samples] + [a, b]
    else:
        nums = [float(x) for x in samples + [lo, hi] if x is not None]
        a = float(lo) if lo is not None else (min(nums) if nums else 0.0)
        b = float(hi) if hi is not None else (max(nums) if nums else 100.0)
        if kind == "int":
            values = list(rng.integers(int(a), int(b) + 1, size=n))
            seeds = [int(s) for s in samples] + [int(a), int(b)]
        else:
            values = list(rng.uniform(a, b, size=n))
            seeds = [float(s) for s in samples] + [a, b]

    # 시드(샘플·양끝 값)와 결측을 서로 겹치지 않는 위치에 배치한다
    order = rng.permutation(n)
    k_null = int(round(n * float(c.get("null_pct") or 0) / 100))
    if float(c.get("null_pct") or 0) > 0:
        k_null = max(k_null, 1)
    k_null = min(k_null, n)
    for pos, v in zip(order[k_null:], seeds):
        values[pos] = v
    nulls = order[:k_null]

    if kind == "date":
        s = pd.Series(sorted(values), dtype="datetime64[ns]")  # 정렬 후 결측을 얹어 날짜 순서를 유지
    elif kind == "str":
        s = pd.Series(values, dtype="str")
    elif kind == "bool":
        s = pd.Series(values, dtype="boolean" if k_null else "bool")
    elif kind == "int":
        s = pd.Series(values, dtype="Int64" if k_null else "int64")
    else:
        s = pd.Series(values, dtype="float64")
    if k_null:
        s.iloc[nulls] = pd.NA if s.dtype.name in ("Int64", "boolean") else np.nan
        if kind == "date":
            s.iloc[nulls] = pd.NaT
    return s
