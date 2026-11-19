"""기상청 API허브 AWS 매분자료 수집기: 파싱·일자료 집계·오류 분류·이어받기. 가짜 서버(MockTransport)만 쓴다."""
from datetime import date

import httpx
import pytest

from jejuagent.data.live.errors import LiveError
from jejuagent.data.live.kma_hub import COLS, KmaHubClient, collect_daily_hub, daily_row, parse_minutes

KEY = "test-key"


def line(tm, ta, rn_day=0.0, stn=90, sep=","):
    v = [tm, stn, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, ta, 0, 0.0, 0.0, 0.0, rn_day, 50.0, 1000.0, 1010.0, 0.0]
    return sep.join(str(x) for x in v)


def day_text(ta=3.0, n=1440, rn_day=0.0, sep=","):
    head = "#START7777\n# YYMMDDHHMI STN WD1\n"
    return head + "\n".join(line(f"20230201{(m // 60):02d}{(m % 60):02d}", ta + (m % 10) / 10, rn_day, sep=sep) for m in range(n)) + "\n#7777END\n"


def test_parse_handles_both_separators_and_missing_marks():
    a, b = parse_minutes(day_text(n=5)), parse_minutes(day_text(n=5, sep=" "))
    assert list(a.columns) == COLS and len(a) == 5 and a.equals(b)
    c = parse_minutes("#x\n" + line("202302010000", -99.7) + "\n")
    assert c["TA"].isna().all() and parse_minutes("#only header\n").empty


def test_daily_row_aggregates_and_drops_short_days():
    df = parse_minutes(day_text(ta=3.0, rn_day=2.5))
    r = daily_row(df, date(2023, 2, 1), "90")
    assert r["tmin"] == 3.0 and r["tmax"] == 3.9 and r["tmean"] == pytest.approx(3.45, abs=0.01) and r["precip"] == 2.5
    assert daily_row(parse_minutes(day_text(n=500)), date(2023, 2, 1), "90") is None   # 유효 분 70% 미만


def client(handler, **kw):
    return KmaHubClient(KEY, httpx.MockTransport(handler), **kw)


def test_request_uses_auth_key_and_single_station_day():
    seen = {}

    def h(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, text=day_text(n=3))
    client(h).minutes("189", date(2023, 2, 1))
    assert seen["stn"] == "189" and seen["tm1"] == "202302010000" and seen["tm2"] == "202302012359" and seen["authKey"] == KEY


@pytest.mark.parametrize("status,kind", [(401, "bad_key"), (403, "bad_key"), (429, "quota"), (500, "network")])
def test_http_errors_are_classified(status, kind):
    with pytest.raises(LiveError) as e:
        client(lambda r: httpx.Response(status)).minutes("90", date(2023, 2, 1))
    assert e.value.kind == kind and KEY not in str(e.value)


def test_no_key_and_network_error_do_not_leak_key():
    with pytest.raises(LiveError) as e:
        KmaHubClient("", httpx.MockTransport(lambda r: httpx.Response(200))).minutes("90", date(2023, 2, 1))
    assert e.value.kind == "no_key"

    def boom(req):
        raise httpx.ConnectError(f"fail {req.url}")
    with pytest.raises(LiveError) as e2:
        client(boom).minutes("90", date(2023, 2, 1))
    assert e2.value.kind == "network" and KEY not in str(e2.value) and KEY not in e2.value.detail


def test_collect_resumes_after_quota_and_snapshots(tmp_path):
    h = lambda r: httpx.Response(200, text=day_text())
    stns = [{"code": c, "name": c, "lat": 33.4, "lon": 126.5, "elevation_m": 10.0} for c in ("90", "92")]
    first = collect_daily_hub(client(h, max_calls=3), stns, date(2023, 2, 1), date(2023, 2, 3), "t", tmp_path)
    assert not first["done"] and first["remaining"] == 3 and first["error"]["kind"] == "quota"
    second = collect_daily_hub(client(h), stns, date(2023, 2, 1), date(2023, 2, 3), "t", tmp_path)
    assert second["done"] and second["calls"] == 3                       # 이미 받은 3건은 다시 받지 않는다
    import json
    snap = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert len(snap["data"]) == 6 and snap["data"][0]["elevation_m"] == 10.0 and snap["meta"]["synthetic"] is False and not (tmp_path / "_state_t.json").exists()
