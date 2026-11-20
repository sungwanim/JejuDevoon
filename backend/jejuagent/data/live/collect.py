"""수집 명령. backend/ 에서 실행:
  python -m jejuagent.data.live.collect hub 20240101 20241231            # 허브 거래·이동평균 -> snapshots/live/
  python -m jejuagent.data.live.collect agri-weather --days 20240101 20241231   # 농업기상(농촌진흥청) 제주 지점 일자료 -> snapshots/live/jeju_weather_daily.json (이어받기)
키는 .env 또는 환경변수에서 읽는다.
"""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from ...catalog.catalog import ROOT


def main(argv=None) -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hub"); h.add_argument("start"); h.add_argument("end")
    w = sub.add_parser("agri-weather"); w.add_argument("--days", nargs=2, required=True); w.add_argument("--max-calls", type=int, default=900)
    args = ap.parse_args(argv)
    from .errors import LiveError
    try:
        if args.cmd == "hub":
            from .registry import LiveRegistry
            reg = LiveRegistry(start=args.start, end=args.end)
            for did in ("jdh_agri_daily_trade", "jdh_agri_trade_moving_avg"):
                df = reg.load(did)
                print(did, df.attrs["data_mode"], len(df))
            for n in reg.notices:
                print(f"[{n['dataset_id']}] {n['cause']} {n['fix']}")
            return 1 if reg.notices else 0
        if args.cmd == "agri-weather":
            from datetime import datetime
            from .agri_weather import AgriWeatherClient, collect_agri_weather
            d0, d1 = (datetime.strptime(x, "%Y%m%d").date() for x in args.days)
            r = collect_agri_weather(AgriWeatherClient(max_calls=args.max_calls), d0, d1)
            print(r)
            if r["error"]:
                print(r["error"]["cause"], r["error"]["fix"])
            return 0 if r["done"] else 1
        return 1   # 모르는 명령은 argparse가 먼저 막는다
    except LiveError as e:
        print(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
