"""수집 명령. backend/ 에서 실행:
  python -m jejuagent.data.live.collect hub 20240101 20241231            # 허브 거래·이동평균 -> snapshots/live/
  python -m jejuagent.data.live.collect stations                          # AWS 지점 원본 -> snapshots/live/kma_aws_stations_raw.json
  python -m jejuagent.data.live.collect aws-daily --spec spec.json --stations 1,2 --years 2015 2024   # 이어받기 지원
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
    sub.add_parser("stations")
    a = sub.add_parser("aws-daily"); a.add_argument("--spec", required=True); a.add_argument("--stations", required=True)
    a.add_argument("--years", nargs=2, type=int, required=True); a.add_argument("--max-calls", type=int, default=10_000)
    args = ap.parse_args(argv)
    from .errors import LiveError
    from .kma import DailySpec, DataGoClient, collect_daily, collect_stations
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
        if args.cmd == "stations":
            print(collect_stations(DataGoClient()))
            return 0
        r = collect_daily(DataGoClient(max_calls=args.max_calls), DailySpec.from_file(args.spec),
                          args.stations.split(","), *args.years)
        print(r)
        if r["error"]:
            print(r["error"]["cause"], r["error"]["fix"])
        return 0 if r["done"] else 1
    except LiveError as e:
        print(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
