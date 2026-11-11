"""드라이런용 가짜 LLM. 질문의 '정답 정보'를 그대로 읽어 응답을 만든다 (실제 GPT-4o가 아니다).

용도는 평가 도구(실행기·지표·리포트)가 끝까지 도는지 키·비용 없이 확인하는 것뿐이다. 정답을 알고 답하므로
이 모드의 지표는 모델 성능이 아니다. 단계는 system 문구로 알아본다 (backend/tests/e2e/fakes.py와 같은 방식).
"""
from __future__ import annotations

import json
import re

from jejuagent.geo.climate import seed_module
from jejuagent.llm.base import CallInfo, LLMClient, LLMError, LLMResponse, prompt_hash

CROPS = ("월동무", "구마늘", "깐마늘", "마늘", "양파", "양배추", "당근", "감귤", "무")
ROLES = {"season": "연산", "crop_group": "채소구분대분류", "crop": "채소구분소분류",
         "area": "면적(ha)", "production": "생산량(톤)", "revenue": "조수입(백만원)"}


def _col(n, d="float", u=""):
    return {"name": n, "dtype": d, "unit": u, "min": None, "max": None}


def _out(i, kind, desc, cols):
    return {"id": i, "kind": kind, "description": desc, "columns": cols}


class ExpectationLLM(LLMClient):
    """set_question()으로 현재 질문을 알려 주면 그 정답 정보에 맞춰 단계별 응답을 낸다."""

    model = "fake"

    def __init__(self):
        self.q: dict = {}
        self.calls = 0

    def set_question(self, q: dict) -> None:
        self.q = q

    # -- 단계별 응답 ---------------------------------------------------------
    def _plan(self, user: str) -> dict:
        q, ex = self.q, self.q["expect"]
        text = q["question"]
        years = re.findall(r"(?:19|20)\d{2}", text)
        cities = [c for c in ("제주시", "서귀포시") if c in text]
        city = cities[0] if len(cities) == 1 else None   # 둘 다 말하면 한 시로 못 박지 않는다
        needs = {"point_analysis": False, "time_series": False, "spatial_comparison": False, **(ex.get("needs") or {})}
        return {"goal": text[:60], "sub_questions": [text], "needs": needs,
                "location": {"kind": "region" if city else "none", "text": city, "lat": None, "lon": None},
                "crop": next((c for c in CROPS if c in text), None), "period": f"{years[0]}년" if years else None,
                "style": "easy" if ex.get("output_format") == "visual" else "unspecified", "missing": [],
                "clarify_question": "어느 위치를 분석할까요? 지도에서 위치를 클릭하고 다시 보내 주세요.",
                "in_domain": ex.get("in_domain") is not False,
                "domain_reason": "제주 농업·기후·시장 데이터 분석이 아닌 요청입니다.",
                "profit_guarantee": bool(ex.get("profit_guarantee")), "tags": []}

    def _select(self, user: str) -> dict:
        ex = self.q["expect"]
        inc = ex.get("must_include") or []
        if not inc and ex.get("status") in ("answered", "partial"):
            inc = ["jeju_vegetable_cultivation"]      # 정답 정보에 데이터가 없는 애매한 질문: 드라이런이 끝까지 돌도록 하나 고른다
        ids = re.findall(r'"id": "([^"]+)"', user.split("[카탈로그]")[1])
        unans = ([{"sub_question": self.q["question"], "reason": "관련 데이터가 일부만 있다"}]
                 if ex.get("status") == "partial" else [])
        return {"feasible": bool(inc), "selected": [{"dataset_id": d, "reason": "정답 정보", "columns": []} for d in inc if d in ids],
                "excluded": [{"dataset_id": d, "reason_code": "irrelevant", "note": "정답 정보"} for d in ids if d not in inc],
                "unanswerable": unans, "infeasible_reason": "" if inc else "요청에 쓸 수 있는 데이터가 없다",
                "needed_data": [] if inc else ["요청 주제의 데이터"]}

    def _tasks(self, user: str) -> dict:
        chosen = user.split("[Profile")[0]
        tasks = []
        if '"dataset_id": "synthetic_aws_daily"' in chosen and '"site_point"' in user:
            tasks.append({"id": "site", "title": "지점 기후 추정", "description": "AWS 관측소 값을 고도 보정 보간으로 지점 기온 지표와 교차검증 오차를 낸다",
                          "inputs": ["synthetic_aws_daily", "site_point", "crop_criteria"], "outputs": [
                              _out("site_markers", "geo", "지점과 관측소 위치", [_col("lat"), _col("lon")]),
                              _out("site_indicators", "metrics", "지점 기온 지표", []),
                              _out("suitability", "table", "기준 비교(꺼져 있으면 빈 표)", [_col("result", "str")]),
                              _out("cross_validation", "table", "교차검증 오차", [_col("mae_daily_c")]),
                              _out("site_limitations", "table", "한계 문구", [_col("text", "str")])]})
        if '"dataset_id": "jdh_agri_daily_trade"' in chosen:
            tasks.append({"id": "price", "title": "품목별 가격 추세와 변동성", "description": "일별 도매가격의 추세와 변동성",
                          "inputs": ["jdh_agri_daily_trade"], "outputs": [
                              _out("variety_trend_stats", "table", "품종별 추세 통계", [_col("variety", "str")]),
                              _out("variety_daily_price", "series", "품종별 일별 가격", [_col("date", "date"), _col("price")])]})
        if '"dataset_id": "jeju_vegetable_cultivation"' in chosen:
            tasks.append({"id": "econ", "title": "작목별 면적당 조수입과 재배면적 추세",
                          "description": "채소 재배현황의 작목별 면적당 조수입, 수량, 단가, 재배면적 증감과 순위",
                          "inputs": ["jeju_vegetable_cultivation"], "outputs": [
                              _out("crop_metrics", "table", "작목·연산별 지표", [_col("crop", "str")]),
                              _out("crop_ranking", "table", "작목 순위", [_col("crop", "str")]),
                              _out("crop_area_trend", "series", "재배면적 추세", [_col("season", "str")]),
                              _out("limitations", "table", "한계", [_col("text", "str")])]})
        if '"dataset_id": "seogwipo_citrus_production"' in chosen:
            tasks.append({"id": "citrus", "title": "감귤 생산 요약", "description": "서귀포시 감귤 생산 데이터의 행 수와 연도 수",
                          "inputs": ["seogwipo_citrus_production"],
                          "outputs": [_out("citrus_summary", "table", "감귤 생산 요약", [_col("n_rows", "int"), _col("n_years", "int")])]})
        if '"dataset_id": "jdh_agri_trade_moving_avg"' in chosen:
            tasks.append({"id": "ma", "title": "이동평균 요약", "description": "가격 이동평균 데이터의 행 수와 품종 수",
                          "inputs": ["jdh_agri_trade_moving_avg"],
                          "outputs": [_out("ma_summary", "table", "이동평균 요약", [_col("n_rows", "int"), _col("n_varieties", "int")])]})
        return {"tasks": tasks}

    def _decide(self, user: str) -> dict:
        new = {"decision": "new", "module_id": "", "reason": "맞는 모듈 없음", "input_binding": [], "role_mapping": []}
        if "[작업] 지점 기후" in user:
            roles = seed_module().MANIFEST["input_roles"]
            return {"decision": "reuse", "module_id": "site_climate", "reason": "verified 모듈이 맞다",
                    "input_binding": [{"module_input": "aws", "task_input": "synthetic_aws_daily"},
                                      {"module_input": "site", "task_input": "site_point"},
                                      {"module_input": "criteria", "task_input": "crop_criteria"}],
                    "role_mapping": [{"input": i, "role": r, "column": r} for i, rs in roles.items() for r in rs]}
        if "[작업] 품목별 가격" in user:
            return {"decision": "reuse", "module_id": "market-price-trend-volatility", "reason": "verified 모듈이 맞다",
                    "input_binding": [{"module_input": "trade", "task_input": "jdh_agri_daily_trade"}],
                    "role_mapping": [{"input": "trade", "role": "date", "column": "baseDate"},
                                     {"input": "trade", "role": "variety", "column": "cultivar"},
                                     {"input": "trade", "role": "price", "column": "averagePrice"}]}
        if "[작업] 작목별 면적당" in user:
            return {"decision": "reuse", "module_id": "market-crop-economics", "reason": "verified 모듈이 맞다",
                    "input_binding": [{"module_input": "cultivation", "task_input": "jeju_vegetable_cultivation"}],
                    "role_mapping": [{"input": "cultivation", "role": k, "column": c} for k, c in ROLES.items()]}
        return new

    def _code(self, user: str) -> dict:
        if "감귤" in user:
            ds, role, col, out, second = "seogwipo_citrus_production", "year", "연도", "citrus_summary", "n_years"
        else:
            ds, role, col, out, second = "jdh_agri_trade_moving_avg", "variety", "cultivar", "ma_summary", "n_varieties"
        code = (f'MANIFEST = {{"title": "요약", "description": "행 수와 고유값 수", "tags": ["summary"], '
                f'"input_roles": {{"{ds}": {{"{role}": "str"}}}}, "params": {{}}, "outputs": ["{out}"]}}\n'
                f'def run(inputs, params):\n    import pandas as pd\n    df = inputs["{ds}"]\n'
                f'    return {{"{out}": pd.DataFrame({{"n_rows": [int(len(df))], "{second}": [int(df["{role}"].nunique())]}})}}\n'
                f'def check(outputs, inputs):\n    o = outputs["{out}"]\n'
                f'    return [] if len(o) == 1 and int(o["n_rows"].iloc[0]) > 0 else ["빈 결과"]\n')
        return {"code": code, "role_mapping": [{"input": ds, "role": role, "column": col}]}

    def _report(self, user: str) -> dict:
        brief = json.loads(user.split("[중간산출물] ")[1].split("\n[답하지")[0])
        blocks = []
        for a in brief:
            if a["kind"] == "geo":
                blocks.append({"type": "map", "artifact_id": a["id"], "title": "지도"})
            elif a["id"] == "variety_daily_price":
                blocks.append({"type": "chart", "artifact_id": a["id"], "x": "date", "y": ["price"], "chart_type": "line", "title": "품종별 일별 가격"})
            elif a["id"] == "crop_area_trend":
                blocks.append({"type": "chart", "artifact_id": a["id"], "x": "season", "y": ["area_ha"], "chart_type": "line", "title": "재배면적 추세"})
            elif a["kind"] == "table":
                blocks.append({"type": "table", "artifact_id": a["id"], "title": a["description"][:30]})
        full = [{"artifact_id": None, "x": None, "y": [], "chart_type": "line", "title": None, "steps": [], "text": None, **b} for b in blocks]
        return {"title": "분석 결과", "summary": "요청한 분석 결과입니다.",
                "sections": [{"heading": "결과", "text": "표와 그래프로 확인하세요.", "blocks": full}], "limits": []}

    # -- LLMClient ------------------------------------------------------------
    def _respond(self, system: str, user: str) -> dict:
        if "요청 규격화 담당" in system:
            return self._plan(user)
        if "데이터 선택 담당" in system:
            return self._select(user)
        if "작업 계획자" in system:
            return self._tasks(user)
        if "기존 모듈을 쓸지" in system:
            return self._decide(user)
        if "pandas 분석 코드를 쓰는" in system:
            return self._code(user)
        if "보고서로 설계하는 담당" in system:
            return self._report(user)
        raise LLMError(f"ExpectationLLM이 모르는 호출입니다: {system[:40]}")

    def structured(self, system, user, schema, *, schema_name="result", purpose=""):
        self.calls += 1
        data = self._respond(system, user)
        n = max(len(system) + len(user), 1)
        info = CallInfo("structured", self.model, prompt_hash(system, user, schema), n // 3,
                        len(json.dumps(data, ensure_ascii=False)) // 3, 1, purpose)
        return LLMResponse(info=info, data=data)

    def text(self, system, user, *, purpose=""):
        raise LLMError("ExpectationLLM은 text 호출을 지원하지 않습니다")
