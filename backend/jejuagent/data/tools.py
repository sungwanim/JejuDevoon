"""고정 도구: 날짜 파싱, 숫자 변환, 지역 필터, 기간 집계, 키 결합. pandas만 사용."""
from __future__ import annotations

import pandas as pd


def parse_dates(s: pd.Series, fmt: str | None = None) -> pd.Series:
    """날짜 문자열/정수(20240102, '2024-01-02' 등)를 datetime으로. 못 읽는 값은 NaT."""
    t = s.astype(str).str.strip()
    if fmt is None and t.str.fullmatch(r"\d{8}").all():
        fmt = "%Y%m%d"
    return pd.to_datetime(t, format=fmt, errors="coerce")


def to_numeric(s: pd.Series, zero_is_missing: bool = False) -> pd.Series:
    """숫자 문자열('1,234.50', ' 3.1 ')을 float로. 못 읽는 값은 NaN. zero_is_missing이면 0을 결측으로(이동평균 API의 0.00)."""
    out = pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce").astype(float)
    return out.mask(out == 0) if zero_is_missing else out


def filter_region(df: pd.DataFrame, col: str, regions) -> pd.DataFrame:
    """행정구역 이름 컬럼이 regions(문자열 하나 또는 목록)에 속하는 행만. 앞뒤 공백은 무시한다."""
    names = [regions] if isinstance(regions, str) else list(regions)
    return df[df[col].astype(str).str.strip().isin([n.strip() for n in names])]


def resample(df: pd.DataFrame, date_col: str, freq: str, agg: dict, by: list[str] | str | None = None) -> pd.DataFrame:
    """기간 집계. freq는 pandas 규칙('MS' 월, 'YS' 연, 'W'), agg는 {컬럼: 'mean'|'sum'|...}, by는 그룹 컬럼."""
    by = [by] if isinstance(by, str) else list(by or [])
    g = df.groupby(by + [pd.Grouper(key=date_col, freq=freq)])
    return g.agg(agg).reset_index()


def join_on(left: pd.DataFrame, right: pd.DataFrame, key, how: str = "left") -> tuple[pd.DataFrame, dict]:
    """키 결합과 결합률 보고. 보고: left_rows, matched_rows, match_rate(0~1), unmatched_keys(최대 10개)."""
    keys = [key] if isinstance(key, str) else list(key)
    m = left.merge(right.drop_duplicates(keys), on=keys, how=how, indicator=True)
    from_left = m[m["_merge"] != "right_only"]
    matched = int((from_left["_merge"] == "both").sum())
    n = len(from_left)
    miss = from_left.loc[from_left["_merge"] == "left_only", keys].drop_duplicates().head(10)
    report = {"left_rows": n, "matched_rows": matched, "match_rate": matched / n if n else 0.0,
              "unmatched_keys": miss.to_dict("records")}
    return m.drop(columns="_merge"), report
