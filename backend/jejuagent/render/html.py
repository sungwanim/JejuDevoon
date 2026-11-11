"""검증된 ReportSpec + RunState -> 독립 HTML 한 파일 (Jinja2, 자동 이스케이프). 형식은 report | visual | map."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

SYNTH_WARNING = "합성 샘플 데이터로 만든 결과입니다. 실제 값이 아닙니다"
REASON_LABEL = {"irrelevant": "요청과 관련 없음", "granularity_mismatch": "공간 단위가 맞지 않음", "out_of_region": "지역이 맞지 않음",
                "out_of_period": "기간이 맞지 않음", "missing_columns": "필요한 컬럼이 없음"}
TASK_LABEL = {"ok": "성공", "failed": "실패", "not_run": "실행 못함", "pending": "대기"}
# 형식별 부분 순서. 공통 섹션(used/process/limits/unanswered/sources)은 어느 형식에나 들어간다.
LAYOUTS = {
    "report": ["summary", "method", "results", "unanswered", "limits", "sources"],
    "visual": ["summary", "flow", "results", "unanswered", "method", "limits", "sources"],
    "map": ["map", "summary", "results", "unanswered", "method", "limits", "sources"],
}
MAX_ROWS, MAX_POINTS = 20, 200

_env = Environment(loader=FileSystemLoader(Path(__file__).parent), autoescape=select_autoescape(["html", "j2"]))


def safe_json(obj) -> str:
    """<script type=application/json> 안에 넣을 JSON. </script> 탈출과 줄 구분자를 막는다."""
    s = json.dumps(obj, ensure_ascii=False, default=str, allow_nan=False)
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _clean(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    return v.item() if hasattr(v, "item") else v


def _cell(v) -> str:
    v = _clean(v)
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.4g}" if abs(v) < 1e6 else f"{v:,.0f}"
    return str(v)


def _table(a) -> dict:
    v = a.value
    if isinstance(v, pd.DataFrame):
        return {"cols": [str(c) for c in v.columns], "rows": [[_cell(x) for x in r] for r in v.head(MAX_ROWS).itertuples(index=False)],
                "total": len(v)}
    flat = v.items() if isinstance(v, dict) else enumerate(v)
    rows = [[str(k), _cell(x) if not isinstance(x, (dict, list)) else json.dumps(x, ensure_ascii=False, default=str)[:200]]
            for k, x in flat]
    return {"cols": ["항목", "값"], "rows": rows[:MAX_ROWS], "total": len(rows)}


def _mermaid(steps: list[str]) -> str:
    lab = [re.sub(r"[^\w\s가-힣.,:/·%\-]", " ", s)[:60].strip() or "단계" for s in steps]
    nodes = [f'n{i}["{t}"]' for i, t in enumerate(lab)]
    return "flowchart TD\n  " + " --> ".join(nodes)


def _chart(b, a) -> dict:
    df = a.value
    step = max(1, -(-len(df) // MAX_POINTS))
    df = df.iloc[::step]
    return {"type": b.get("chart_type", "line"), "labels": df[b["x"]].astype(str).tolist(),
            "series": [{"name": c, "data": [_clean(x) for x in pd.to_numeric(df[c], errors="coerce")]} for c in b["y"]]}


def _points(a, plan_loc: dict | None) -> list[dict]:
    pts = []
    if plan_loc and plan_loc.get("lat") is not None and plan_loc.get("lon") is not None:
        pts.append({"lat": plan_loc["lat"], "lon": plan_loc["lon"], "label": "분석 지점"})
    if a is not None:
        df = a.value.head(MAX_POINTS)
        lab = next((c for c in df.columns if c not in ("lat", "lon") and not pd.api.types.is_numeric_dtype(df[c])), None)
        for i in range(len(df)):
            lat, lon = pd.to_numeric(df.iloc[i]["lat"], errors="coerce"), pd.to_numeric(df.iloc[i]["lon"], errors="coerce")
            if pd.notna(lat) and pd.notna(lon):
                pts.append({"lat": float(lat), "lon": float(lon), "label": str(df.iloc[i][lab]) if lab else ""})
    return pts


def _prep_block(b: dict, artifacts: dict, plan_loc: dict | None, n: list[int]) -> dict:
    n[0] += 1
    out = {"type": b["type"], "title": b.get("title") or "", "uid": f"b{n[0]}"}
    a = artifacts.get(b.get("artifact_id") or "")
    if b["type"] == "chart":
        out["chart"] = safe_json(_chart(b, a))
        out["table"] = _table(a)
    elif b["type"] == "table":
        out["table"] = _table(a)
    elif b["type"] == "map":
        out["points"] = _points(a, plan_loc)
        out["uid_artifacts"] = [a.id] if a is not None else []
        out["map"] = safe_json(out["points"])
    elif b["type"] == "flow":
        out["steps"] = b["steps"]
        out["mermaid"] = safe_json(_mermaid(b["steps"]))
    elif b["type"] == "callout":
        out["text"] = b["text"]
    return out


def process_flow(state, catalog_by_id: dict) -> list[str]:
    """분석 과정 흐름도 단계 (코드가 만든다. 숫자 없음)."""
    ids = _used_ids(state)
    steps = ["요청 해석: " + ((state.plan or {}).get("goal") or state.request)[:40]]
    if ids:
        steps.append("데이터: " + ", ".join((catalog_by_id.get(i) or {}).get("title") or i for i in ids)[:60])
    steps += [f"분석: {t.get('title') or t['id']}" for t in state.tasks]
    steps.append("결과 정리")
    return steps


def _used_ids(state) -> list[str]:
    if state.selection:
        return [s["dataset_id"] for s in state.selection.get("selected", [])]
    return list(state.data)


def _site_limits(state) -> list[str]:
    """12의 지점 기후 모듈 결과가 있으면 그 한계 문구(geo.climate.limitations + 모듈이 낸 limitations 표)를 그대로 싣는다."""
    from ..geo.climate import limitations, seed_module
    title = seed_module().MANIFEST["title"]
    mine = [a for a in state.artifacts.values() if a.module_title == title]
    if not mine:
        return []
    syn = bool((state.extra or {}).get("module_params", {}).get("synthetic"))
    texts = [t for a in mine if isinstance(a.value, pd.DataFrame) and list(a.value.columns) == ["text"] for t in a.value["text"]]
    return list(dict.fromkeys([*limitations(syn), *texts]))


def _crop_limits(state) -> list[str]:
    """채소 재배현황 모듈(market/crop_economics.py) 결과가 있으면 그 한계 문구(LIMITATIONS + 모듈이 낸 표)를 싣는다."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "modules_seed" / "market" / "crop_economics.py"
    spec = importlib.util.spec_from_file_location("crop_economics_seed", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    mine = [a for a in state.artifacts.values() if a.module_title == m.MANIFEST["title"]]
    if not mine:
        return []
    texts = [t for a in mine if isinstance(a.value, pd.DataFrame) and list(a.value.columns) == ["text"] for t in a.value["text"]]
    return list(dict.fromkeys([*m.LIMITATIONS, *texts]))


def auto_limits(state, used: list[dict]) -> list[str]:
    plan, out = state.plan or {}, []
    needs = plan.get("needs") or {}
    if any(d["synthetic"] for d in used):
        out.append("거래 데이터가 합성 샘플이라 가격·거래량 값은 실제와 다릅니다. 실데이터가 연결되면 결과가 달라집니다.")
    if needs.get("point_analysis") or plan.get("output_format") == "map":
        out.append("지점의 고도는 90m 격자 DEM에서 읽은 값이라 격자 크기만큼의 오차가 있고, 경사·일사는 반영하지 않았습니다.")
        out.append("한계온도(작물이 견디는 임계 기온)로 재배 가능 여부를 판정하지 않았습니다.")
    excl = (state.selection or {}).get("excluded", [])
    if any(x.get("reason_code") == "out_of_region" for x in excl) or \
       (plan.get("crop") and "감귤" in plan["crop"] and "제주시" in ((plan.get("location") or {}).get("text") or "")):
        out.append("감귤 생산 데이터는 서귀포시만 있고 제주시 데이터는 없습니다.")
    out += _site_limits(state)
    out += _crop_limits(state)
    if state.limit_hit:
        out.append("실행 상한(" + ("LLM 호출 수" if state.limit_hit == "llm_calls" else "시간") + ")에 걸려 그때까지의 결과로 만들었습니다.")
    return out


def render_html(state, spec: dict, catalog: list[dict], removed: list[str], fallback: bool) -> str:
    plan = state.plan or {}
    fmt = plan.get("output_format") if plan.get("output_format") in LAYOUTS else "report"
    cat = {e["id"]: e for e in catalog}
    sel = {s["dataset_id"]: s for s in (state.selection or {}).get("selected", [])}
    used = []
    for i in _used_ids(state):
        e = cat.get(i, {})
        used.append({"id": i, "title": e.get("title") or i, "reason": (sel.get(i) or {}).get("reason", ""),
                     "role": (sel.get(i) or {}).get("role", ""), "synthetic": bool(e.get("synthetic")),
                     "source": e.get("source", ""), "license": e.get("license", ""), "notes": e.get("notes", "")})
    excluded = [{"id": x["dataset_id"], "title": (cat.get(x["dataset_id"]) or {}).get("title") or x["dataset_id"],
                 "why": REASON_LABEL.get(x.get("reason_code"), x.get("reason_code", "")), "note": x.get("note", "")}
                for x in (state.selection or {}).get("excluded", [])]
    tasks = []
    for t in state.tasks:
        arts = [state.artifacts[i] for i in t.get("artifact_ids", []) if i in state.artifacts]
        tasks.append({"id": t["id"], "title": t.get("title", ""), "status": TASK_LABEL.get(t.get("status"), t.get("status", "")),
                      "attempts": len(t.get("attempts", [])), "artifacts": [a.id for a in arts],
                      # 07이 모듈 저장소를 붙이면 module_id/module_version을 task에 넣는다. 없으면 코드 해시로 식별한다.
                      "module": t.get("module_id") or (arts[0].module_title if arts else ""),
                      "version": t.get("module_version") or (arts[0].code_hash if arts else "")})
    unanswered, seen = [], set()
    for u in [*state.unanswered, *[{"what": f"데이터 로드 실패: {f.get('dataset_id')}", "why": str(f.get("error", ""))}
                                   for f in state.load_failures]]:
        if (u["what"], u["why"]) not in seen:
            seen.add((u["what"], u["why"]))
            unanswered.append({"what": u["what"], "why": u["why"]})

    n = [0]
    loc = plan.get("location")
    sections = [{"heading": s["heading"], "text": s["text"],
                 "blocks": [_prep_block(b, state.artifacts, loc, n) for b in s["blocks"]]} for s in spec["sections"]]
    map_blocks = []
    if fmt == "map":  # 지도 중심: 지도 블록을 맨 위로. LLM이 안 냈으면 분석 지점 하나짜리 지도를 둔다
        for s in sections:
            map_blocks += [b for b in s["blocks"] if b["type"] == "map"]
            s["blocks"] = [b for b in s["blocks"] if b["type"] != "map"]
        for a in state.artifacts.values():   # 위경도가 있는 geo 산출물(site_markers 등)은 LLM이 빼먹어도 지도에 올린다
            shown = any(b["type"] == "map" and a.id in b["uid_artifacts"] for b in map_blocks)
            if a.kind == "geo" and not shown and isinstance(a.value, pd.DataFrame) and {"lat", "lon"} <= set(a.value.columns):
                map_blocks.append(_prep_block({"type": "map", "title": a.description or a.id, "artifact_id": a.id}, state.artifacts, loc, n))
        if not map_blocks:
            map_blocks = [_prep_block({"type": "map", "title": "분석 지점"}, state.artifacts, loc, n)]
    flow = _prep_block({"type": "flow", "title": "분석 흐름", "steps": process_flow(state, cat)}, state.artifacts, loc, n)

    limits = [*spec["limits"], *auto_limits(state, used)]
    return _env.get_template("report.html.j2").render(
        fmt=fmt, parts=LAYOUTS[fmt], title=spec["title"] or plan.get("goal") or "분석 결과", summary=spec["summary"],
        sections=sections, map_blocks=map_blocks, flow=flow, used=used, excluded=excluded, tasks=tasks,
        unanswered=unanswered, limits=limits,
        notices=list(dict.fromkeys(n for n in [plan.get("notice"), *(state.extra or {}).get("notices", [])] if n)),
        synth=any(d["synthetic"] for d in used), synth_warning=SYNTH_WARNING,
        synth_ids=[d["title"] for d in used if d["synthetic"]], removed=len(removed), fallback=fallback,
        partial=bool(unanswered), status_note=state.message if state.limit_hit else "")
