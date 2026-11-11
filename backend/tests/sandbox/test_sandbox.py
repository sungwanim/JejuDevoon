import subprocess
import sys
import textwrap

import pandas as pd
import pytest

from jejuagent.sandbox import (
    COLUMN_ROLE_MISMATCH, CONTRACT_ERROR, DATA_PROBLEM, FORBIDDEN, FORMAT_ERROR, SYNTAX_ERROR, TIMEOUT,
    VALIDATION_FAILED, make_mock_dataframe, run_generated_code,
)

ART = [{"id": "avg", "kind": "table", "columns": [{"name": "variety", "dtype": "str"}, {"name": "price", "dtype": "float"}]}]
PRICES = pd.DataFrame({"거래일자": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
                       "품종": ["무", "무", "당근"], "평균가": [100.0, 200.0, 300.0]})
MAPPING = {"prices": {"date": "거래일자", "variety": "품종", "price": "평균가"}}


def mod(run_body="return {'avg': inputs['prices'].groupby('variety', as_index=False)['price'].mean()}",
        check_body="return []", header="", outputs="['avg']"):
    return (header + "\nMANIFEST = {'title': 't', 'description': 'd', 'tags': [], "
            "'input_roles': {'prices': {'date': 'date', 'variety': 'str', 'price': 'float'}}, "
            f"'params': {{}}, 'outputs': {outputs}}}\n"
            f"def run(inputs, params):\n{textwrap.indent(run_body, '    ')}\n"
            f"def check(outputs, inputs):\n{textwrap.indent(check_body, '    ')}\n")


def go(code, **kw):
    kw.setdefault("inputs", PRICES_IN)
    kw.setdefault("role_mapping", MAPPING)
    kw.setdefault("artifacts", ART)
    return run_generated_code(code, **kw)


PRICES_IN = {"prices": PRICES}


# --- 성공 / 계약

def test_success():
    r = go(mod())
    assert r.ok and r.failure is None and r.stage == "done"
    assert r.outputs["avg"].set_index("variety")["price"].to_dict() == {"무": 150.0, "당근": 300.0}
    assert r.elapsed_s > 0


def test_params_and_stdout_passed():
    r = go(mod("print('hi')\nreturn {'avg': inputs['prices'].assign(price=params['k'])}"), params={"k": 7.0})
    assert r.ok and (r.outputs["avg"]["price"] == 7.0).all() and "hi" in r.stdout


@pytest.mark.parametrize("code", [
    "x = 1",
    "MANIFEST = {'title': 't'}\ndef run(i, p): return {}\ndef check(o, i): return []",
    mod().replace("def check(outputs, inputs):\n    return []\n", ""),
    mod().replace("def run(inputs, params)", "def run(inputs)"),
    "MANIFEST = dict(title='t')\ndef run(i, p): return {}\ndef check(o, i): return []",
])
def test_contract_violations(code):
    r = go(code)
    assert not r.ok and r.failure == CONTRACT_ERROR


def test_syntax_error():
    r = go("def run(:\n")
    assert r.failure == SYNTAX_ERROR and "문법" in r.message


# --- 정적 검사

@pytest.mark.parametrize("header", [
    "import os", "import subprocess", "import socket", "from os import system", "import requests",
    "import pandas.io.common\nimport sys", "from . import x",
    "eval('1')", "exec('x=1')", "__import__('os')", "compile('1','a','eval')",
    "open('/etc/x.txt', 'w')", "open('../x.txt', 'w')", "open('C:/x.txt', 'w')",
    "pd = None\npd.DataFrame().to_csv('/tmp/out.csv')",
])
def test_forbidden_static(header):
    r = go(mod(header=header))
    assert not r.ok and r.failure == FORBIDDEN and r.stage == "static"
    assert r.problems and r.elapsed_s < 1  # 프로세스를 띄우기 전에 차단


def test_forbidden_call_inside_function():
    r = go(mod("return {'avg': eval('1')}"))
    assert r.failure == FORBIDDEN and "eval" in r.message


def test_allowed_imports_pass():
    r = go(mod(header="import math, statistics, datetime, json, re\nimport numpy as np\nimport pandas as pd\nfrom scipy import stats"))
    assert r.ok


def test_open_read_literal_and_relative_write_not_flagged_statically():
    r = go(mod("open('out.txt', 'w').write('x')\nreturn {'avg': inputs['prices'].groupby('variety', as_index=False)['price'].mean()}"))
    assert r.ok  # 작업 폴더 안 쓰기는 허용


# --- 격리: 환경변수, 네트워크, 폴더 한정

def test_secret_env_not_visible(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("JEJU_HUB_PROJECT_KEY", "k2")
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "k3")
    code = mod("import os\nimport pandas as pd\n"
               "return {'avg': pd.DataFrame({'variety': sorted(os.environ), 'price': 1.0})}",
               check_body="return []")
    r = go(code, extra_allowed_imports=["os"])
    assert r.ok
    names = set(r.outputs["avg"]["variety"].str.upper())
    assert not names & {"OPENAI_API_KEY", "JEJU_HUB_PROJECT_KEY", "DATA_GO_KR_SERVICE_KEY"}
    assert "test-key" not in r.stdout


def test_isolated_mode_flag():
    r = go(mod("import sys\nimport pandas as pd\nreturn {'avg': pd.DataFrame({'variety': ['x'], 'price': [float(sys.flags.isolated)]})}"),
           extra_allowed_imports=["sys"])
    assert r.ok and r.outputs["avg"]["price"][0] == 1.0


@pytest.mark.parametrize("body", [
    "import socket as s\ns.socket()",
    "import socket as s\ns.create_connection(('127.0.0.1', 9))",
    "import socket as s\ns.getaddrinfo('example.com', 80)",
    "import urllib.request as ur\nur.urlopen('http://127.0.0.1:9')",
])
def test_network_blocked(body):  # 별칭 import로 정적 검사를 우회해 런타임 차단만 확인
    r = go(mod(body + "\nreturn {}"), extra_allowed_imports=["socket", "urllib"])
    assert not r.ok and r.failure == FORBIDDEN and "네트워크" in r.message


def test_write_outside_workdir_blocked_at_runtime(tmp_path):
    target = tmp_path / "evil.txt"
    # 경로를 런타임에 조립해 정적 검사를 우회한 경우
    body = f"p = ''.join({list(str(target))!r})\nopen(p, 'w').write('x')\nreturn {{}}"
    r = go(mod(body))
    assert r.failure == FORBIDDEN and "작업 폴더 밖" in r.message
    assert not target.exists()


def test_workdir_is_cwd_and_deleted():
    r = go(mod("import os\nimport pandas as pd\nreturn {'avg': pd.DataFrame({'variety': [os.getcwd()], 'price': [1.0]})}"),
           extra_allowed_imports=["os"])
    cwd = r.outputs["avg"]["variety"][0]
    assert "jeju_sbx_" in cwd
    import os
    assert not os.path.exists(cwd)


# --- 시간 초과

def _pid_alive(pid):
    # tasklist 출력은 지역 코드 페이지(cp949 등)라 텍스트로 해석하지 않고 바이트로 찾는다 (PYTHONUTF8=1에서도 안전)
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True).stdout
    return f'"{pid}"'.encode() in out


@pytest.mark.skipif(sys.platform != "win32", reason="tasklist 사용")
def test_timeout_kills_process(tmp_path):
    pidfile = tmp_path / "pid.txt"
    body = f"import os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(30)\nreturn {{}}"
    # pidfile은 작업 폴더 밖이라 가드에 걸리므로 가드 이전에 쓸 수 없다 -> 작업 폴더를 tmp_path로 지정하고 상대 경로 사용
    body = "import os, time\nopen('pid.txt', 'w').write(str(os.getpid()))\ntime.sleep(30)\nreturn {}"
    import threading
    import time as _t
    found = {}

    def watch():  # 작업 폴더가 삭제되기 전에 pid를 읽는다
        for _ in range(100):
            for p in tmp_path.glob("jeju_sbx_*/pid.txt"):
                try:
                    found["pid"] = int(p.read_text())
                    return
                except (ValueError, OSError):
                    pass
            _t.sleep(0.1)

    th = threading.Thread(target=watch)
    th.start()
    r = go(mod(body), timeout_s=5, extra_allowed_imports=["os", "time"], work_dir=str(tmp_path))
    th.join()
    assert r.failure == TIMEOUT and r.stage == "run" and 4.5 < r.elapsed_s < 15
    assert "pid" in found, "자식 PID를 읽지 못함"
    assert not _pid_alive(found["pid"])


def test_timeout_is_configurable_and_fast_code_unaffected():
    assert go(mod(), timeout_s=60).ok
    r = go(mod("while True:\n    pass"), timeout_s=1.5)
    assert r.failure == TIMEOUT and "1.5" in r.message


# --- 출력 스키마

@pytest.mark.parametrize("body,needle", [
    ("return {'other': inputs['prices']}", "id 불일치"),
    ("return {'avg': inputs['prices'], 'extra': 1}", "id 불일치"),
    ("return {'avg': {'a': 1}}", "DataFrame"),
    ("import pandas as pd\nreturn {'avg': pd.DataFrame({'variety': ['a']})}", "price"),
    ("import pandas as pd\nreturn {'avg': pd.DataFrame({'variety': ['a'], 'price': ['x']})}", "타입 불일치"),
])
def test_schema_mismatch(body, needle):
    r = go(mod(body))
    assert not r.ok and r.failure == FORMAT_ERROR and r.stage == "schema" and needle in r.message


def test_metrics_kind_and_manifest_outputs_fallback():
    r = go(mod("return {'avg': {'cv': 0.2}}"), artifacts=[{"id": "avg", "kind": "metrics"}])
    assert r.ok
    r = go(mod("return {'zzz': 1}"), artifacts=None)  # MANIFEST outputs와 비교
    assert r.failure == FORMAT_ERROR


def test_run_must_return_dict():
    r = go(mod("return [1]"))
    assert r.failure == FORMAT_ERROR and "dict" in r.message


# --- 검증 함수 / 공통 검사

def test_check_problems_propagate():
    r = go(mod(check_body="return ['평균가가 음수', '품종 누락']"))
    assert not r.ok and r.failure == VALIDATION_FAILED and r.stage == "check"
    assert r.problems == ["평균가가 음수", "품종 누락"]
    assert r.outputs["avg"] is not None


def test_check_receives_outputs_and_inputs():
    r = go(mod(check_body="return [] if len(outputs['avg']) == inputs['prices']['variety'].nunique() else ['x']"))
    assert r.ok


def test_check_must_return_list():
    assert go(mod(check_body="return None")).failure == FORMAT_ERROR


def test_common_check_all_missing():
    r = go(mod("import numpy as np, pandas as pd\nreturn {'avg': pd.DataFrame({'variety': [None, None], 'price': [np.nan, np.nan]})}"))
    assert r.failure == VALIDATION_FAILED and "결측" in r.message


def test_common_check_empty_output_is_data_problem():
    r = go(mod("return {'avg': inputs['prices'].iloc[0:0]}"))
    assert r.failure == DATA_PROBLEM and r.stage == "common"


def test_value_range_check():
    r = go(mod(), value_ranges={"price": (0, 200)})
    assert r.failure == VALIDATION_FAILED and "상식 범위" in r.message


# --- 실패 분류 (대표 오류)

@pytest.mark.parametrize("body,expected", [
    ("return {'avg': inputs['prices'][['nope']]}", COLUMN_ROLE_MISMATCH),
    ("return {'avg': inputs['nothere']}", COLUMN_ROLE_MISMATCH),
    ("return {'avg': inputs['prices'].nope}", COLUMN_ROLE_MISMATCH),
    ("import pandas as pd\nreturn {'avg': pd.to_datetime(pd.Series(['not a date']))}", FORMAT_ERROR),
    ("return {'avg': float('abc')}", FORMAT_ERROR),
    ("return {'avg': 'a' + 1}", FORMAT_ERROR),
    ("raise DataProblem('필요한 기간 없음')", DATA_PROBLEM),
    ("df = inputs['prices']\nreturn {'avg': df[df['price'] > 1e9].iloc[0]}", DATA_PROBLEM),
    ("return {'avg': max([])}", DATA_PROBLEM),
    ("return {'avg': 1 / 0}", "runtime_error"),
])
def test_classification_runtime_errors(body, expected):
    r = go(mod(body))
    assert not r.ok and r.failure == expected and r.stage == "run", (r.failure, r.message)
    assert "traceback" in r.details


def test_role_mapping_mismatch_reports_available_columns():
    r = go(mod(), role_mapping={"prices": {"date": "거래일자", "variety": "없는컬럼", "price": "평균가"}})
    assert r.failure == COLUMN_ROLE_MISMATCH and r.stage == "inputs"
    assert "품종" in r.details["available_columns"]["prices"]


def test_manifest_roles_missing_in_input():
    r = go(mod(), role_mapping=None)  # 컬럼 이름이 한글이라 역할 컬럼(date 등)이 없다
    assert r.failure == COLUMN_ROLE_MISMATCH and "date" in r.message


def test_empty_input_is_data_problem():
    r = go(mod(), inputs={"prices": PRICES.iloc[0:0]})
    assert r.failure == DATA_PROBLEM and r.stage == "inputs"


def test_same_code_different_column_names_via_role_mapping():
    other = PRICES.rename(columns={"거래일자": "d", "품종": "v", "평균가": "p"})
    r = go(mod(), inputs={"prices": other}, role_mapping={"prices": {"date": "d", "variety": "v", "price": "p"}})
    assert r.ok


# --- mock

PROFILE = {"dataset_id": "x", "n_rows": 12034, "encoding": "cp949", "columns": [
    {"name": "평균가", "dtype": "float", "null_pct": 10.0, "min": 120, "max": 9800, "n_unique": 3011, "samples": [1520, 980, 2210]},
    {"name": "품종", "dtype": "str", "null_pct": 0, "min": None, "max": None, "n_unique": 3, "samples": ["무", "당근", "마늘"]},
    {"name": "거래일자", "dtype": "date", "null_pct": 0, "min": "2020-01-01", "max": "2020-12-31", "n_unique": 300, "samples": ["2020-03-01"]},
    {"name": "건수", "dtype": "int", "null_pct": 0, "min": 1, "max": 5, "n_unique": 5, "samples": [1, 2, 3]},
]}


def test_mock_reflects_profile():
    df = make_mock_dataframe(PROFILE, n_rows=100)
    assert len(df) == 100 and list(df.columns) == ["평균가", "품종", "거래일자", "건수"]
    p = df["평균가"]
    assert p.isna().sum() == 10 and p.min() >= 120 and p.max() <= 9800
    assert {1520, 980, 2210} <= set(p.dropna())
    assert set(df["품종"]) == {"무", "당근", "마늘"}
    assert pd.api.types.is_datetime64_any_dtype(df["거래일자"])
    assert df["거래일자"].min() >= pd.Timestamp("2020-01-01") and df["거래일자"].max() <= pd.Timestamp("2020-12-31")
    assert pd.api.types.is_integer_dtype(df["건수"]) and df["건수"].between(1, 5).all()
    assert df.equals(make_mock_dataframe(PROFILE, n_rows=100))  # 시드 고정이면 재현


def test_mock_run_uses_profile_and_same_code():
    prof = {"prices": PROFILE}
    mapping = {"prices": {"date": "거래일자", "variety": "품종", "price": "평균가"}}
    r = run_generated_code(mod(), profiles=prof, role_mapping=mapping, artifacts=ART, mock_rows=60)
    assert r.ok and r.details["mock"] is True
    assert set(r.outputs["avg"]["variety"]) == {"무", "당근", "마늘"}
    # 같은 코드를 실데이터로도 실행
    assert go(mod()).ok


def test_mock_run_catches_column_error():
    prof = {"prices": PROFILE}
    mapping = {"prices": {"date": "거래일자", "variety": "품종", "price": "없는컬럼"}}
    r = run_generated_code(mod(), profiles=prof, role_mapping=mapping, artifacts=ART)
    assert r.failure == COLUMN_ROLE_MISMATCH and r.details["mock"] is True
