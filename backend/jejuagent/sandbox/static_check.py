"""생성 코드 정적 검사: 문법, 코드 계약(MANIFEST/run/check), import 허용 목록, 금지 호출.

LLM 실수를 걸러내는 용도다. getattr 등을 이용한 우회는 막지 않는다 (악의적 코드 방어 아님).
"""
from __future__ import annotations

import ast
import os

ALLOWED_IMPORTS = frozenset({
    # 데이터
    "pandas", "numpy", "scipy",
    # 표준 라이브러리(수학·통계·날짜·문자열·자료구조)
    "math", "statistics", "datetime", "json", "re", "collections", "itertools",
    "functools", "typing", "calendar", "decimal", "fractions", "copy", "operator",
    "dataclasses", "numbers", "__future__",
    # 고정 도구 라이브러리 (티켓 03이 만든다. 여기서는 이름만 허용)
    "jejukit",
})

MANIFEST_KEYS = ("title", "description", "tags", "input_roles", "params", "outputs")

FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__", "input", "breakpoint", "exit", "quit"})
FORBIDDEN_DOTTED = ("os.system", "os.popen", "os.spawn", "os.exec", "os.startfile",
                    "subprocess.", "socket.", "shutil.", "urllib.", "requests.", "ctypes.")
FORBIDDEN_ATTRS = frozenset({"__subclasses__", "__globals__", "__builtins__", "__import__"})
# 첫 인자가 경로 문자열일 수 있는 쓰기 함수
WRITE_FUNCS = frozenset({"open", "to_csv", "to_parquet", "to_excel", "to_pickle", "to_json",
                         "to_feather", "to_hdf", "write_text", "write_bytes", "mkdir", "savetxt", "save"})
_WRITE_MODE = set("wax+")


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _outside_path(value: str) -> bool:
    return os.path.isabs(value) or value.startswith(("/", "\\")) or value[1:2] == ":" or ".." in value.replace("\\", "/").split("/")


def check_code(code: str, extra_allowed_imports=()) -> tuple[str | None, list[str], dict | None]:
    """(실패 종류, 메시지 목록, MANIFEST). 실패 종류: 'syntax' | 'forbidden' | 'contract' | None."""
    try:
        tree = ast.parse(code, filename="generated.py")
    except SyntaxError as e:
        return "syntax", [f"문법 오류 (줄 {e.lineno}): {e.msg}"], None

    allowed = ALLOWED_IMPORTS | set(extra_allowed_imports)
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in allowed:
                    bad.append(f"줄 {node.lineno}: 허용되지 않은 import '{a.name}'")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in allowed:
                bad.append(f"줄 {node.lineno}: 허용되지 않은 import '{'.' * node.level}{node.module or ''}'")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            bad.append(f"줄 {node.lineno}: 금지된 속성 '{node.attr}'")
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            last = name.rsplit(".", 1)[-1]
            if name in FORBIDDEN_CALLS or name.startswith(FORBIDDEN_DOTTED):
                bad.append(f"줄 {node.lineno}: 금지된 호출 '{name}'")
            if last in WRITE_FUNCS and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str) and _outside_path(node.args[0].value):
                mode = ""
                if last == "open":
                    m = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
                    mode = m.value if isinstance(m, ast.Constant) and isinstance(m.value, str) else ""
                if last != "open" or _WRITE_MODE & set(mode):
                    bad.append(f"줄 {node.lineno}: 작업 폴더 밖 파일 쓰기 '{name}({node.args[0].value!r})'")
    if bad:
        return "forbidden", bad, None

    manifest, problems = None, []
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "MANIFEST" for t in n.targets):
            try:
                manifest = ast.literal_eval(n.value)
            except ValueError:
                problems.append("MANIFEST는 리터럴 dict여야 한다 (함수 호출·변수 참조 금지)")
    if manifest is None and not problems:
        problems.append("MANIFEST가 없다")
    elif isinstance(manifest, dict):
        missing = [k for k in MANIFEST_KEYS if k not in manifest]
        if missing:
            problems.append(f"MANIFEST에 필요한 키가 없다: {missing}")
        elif not isinstance(manifest["outputs"], list) or not isinstance(manifest["input_roles"], dict):
            problems.append("MANIFEST의 outputs는 list, input_roles는 dict여야 한다")
    elif manifest is not None:
        problems.append("MANIFEST는 dict여야 한다")
    for fn in ("run", "check"):
        f = funcs.get(fn)
        if f is None:
            problems.append(f"함수 {fn}(...)가 없다")
        elif len(f.args.args) + len(f.args.posonlyargs) < 2 and f.args.vararg is None:
            problems.append(f"{fn}()은 인자 2개(run: inputs, params / check: outputs, inputs)를 받아야 한다")
    if problems:
        return "contract", problems, None
    return None, [], manifest
