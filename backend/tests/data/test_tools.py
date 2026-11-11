import numpy as np
import pandas as pd

from jejuagent.data import filter_region, join_on, parse_dates, resample, to_numeric


def test_parse_dates_yyyymmdd_and_bad():
    s = parse_dates(pd.Series(["20240102", "20240103"]))
    assert s.iloc[0] == pd.Timestamp("2024-01-02")
    assert pd.isna(parse_dates(pd.Series(["2024-01-02", "x"])).iloc[1])


def test_to_numeric_strings_commas_and_zero_missing():
    s = pd.Series(["1,234.50", " 3.1 ", "0.00", "abc"])
    assert to_numeric(s).tolist()[:3] == [1234.5, 3.1, 0.0] and np.isnan(to_numeric(s).iloc[3])
    assert to_numeric(s, zero_is_missing=True).isna().tolist() == [False, False, True, True]


def test_filter_region_ignores_whitespace():
    df = pd.DataFrame({"읍면동": ["효돈동 ", "대정읍", "성산읍"], "v": [1, 2, 3]})
    assert filter_region(df, "읍면동", "효돈동")["v"].tolist() == [1]
    assert len(filter_region(df, "읍면동", ["대정읍", "성산읍"])) == 2


def test_resample_monthly_by_group():
    df = pd.DataFrame({"d": pd.to_datetime(["2024-01-01", "2024-01-15", "2024-02-01"]), "c": ["a", "a", "a"], "p": [1.0, 3.0, 5.0]})
    r = resample(df, "d", "MS", {"p": "mean"}, by="c")
    assert r["p"].tolist() == [2.0, 5.0]


def test_join_on_reports_match_rate():
    left = pd.DataFrame({"k": ["a", "b", "c", "d"], "x": range(4)})
    right = pd.DataFrame({"k": ["a", "b", "z"], "y": [10, 20, 30]})
    out, rep = join_on(left, right, "k")
    assert len(out) == 4 and rep["matched_rows"] == 2 and rep["match_rate"] == 0.5
    assert {"k": "c"} in rep["unmatched_keys"]
