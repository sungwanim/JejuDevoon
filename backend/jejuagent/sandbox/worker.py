"""자식 프로세스 진입점. `python -I -X utf8 worker.py <작업폴더>`로만 실행된다 (jejuagent를 import하지 않는다).

작업폴더의 payload.pkl(code, inputs, params, extra_sys_paths)을 읽어 코드를 실행하고
result.pkl에 결과를 쓴다. 네트워크 차단·작업 폴더 밖 쓰기 차단 훅을 코드 실행 직전에 설치한다.
"""
import builtins
import contextlib
import io
import os
import pickle
import sys
import traceback


class SandboxViolation(Exception):
    pass


class DataProblem(Exception):
    """생성 코드가 '필터 후 빈 데이터·필요한 기간 없음'을 알릴 때 raise한다 (builtins로 주입됨)."""


def install_guards(workdir):
    import socket

    class _Blocked(socket.socket):
        def __init__(self, *a, **k):
            raise SandboxViolation("네트워크 접근이 차단되어 있다")

    def _deny(*a, **k):
        raise SandboxViolation("네트워크 접근이 차단되어 있다")

    socket.socket = _Blocked
    for name in ("create_connection", "create_server", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "socketpair"):
        if hasattr(socket, name):
            setattr(socket, name, _deny)

    root = os.path.normcase(os.path.realpath(workdir))
    real_open = io.open

    def guarded_open(file, mode="r", *a, **k):
        if isinstance(file, (str, bytes, os.PathLike)) and set("wax+") & set(mode):
            p = os.path.normcase(os.path.realpath(os.fsdecode(file)))
            if p != root and not p.startswith(root + os.sep):
                raise SandboxViolation(f"작업 폴더 밖 파일 쓰기 차단: {os.fsdecode(file)}")
        return real_open(file, mode, *a, **k)

    builtins.open = io.open = guarded_open
    builtins.DataProblem = DataProblem


def main():
    workdir = os.path.realpath(sys.argv[1])
    os.chdir(workdir)
    with open(os.path.join(workdir, "payload.pkl"), "rb") as f:
        payload = pickle.load(f)
    sys.path.extend(payload["extra_sys_paths"])
    result = {"ok": False}
    out = io.StringIO()
    try:
        install_guards(workdir)
        ns = {"__name__": "generated_module"}
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            exec(compile(payload["code"], "generated.py", "exec"), ns)
            outputs = ns["run"](payload["inputs"], payload["params"])
            if not isinstance(outputs, dict):
                raise TypeError(f"run()은 dict를 반환해야 한다 (받은 값: {type(outputs).__name__})")
            result["outputs"] = outputs
            # check는 run이 건드리지 않은 새 입력으로 호출한다
            with open(os.path.join(workdir, "payload.pkl"), "rb") as f:
                fresh = pickle.load(f)["inputs"]
            problems = ns["check"](outputs, fresh)
            if not isinstance(problems, (list, tuple)):
                raise TypeError(f"check()는 문제 목록(list[str])을 반환해야 한다 (받은 값: {type(problems).__name__})")
            result["problems"] = [str(p) for p in problems]
            result["ok"] = True
    except BaseException as e:  # noqa: BLE001 - 모든 실패를 부모에 전달
        result["error"] = {
            "type": type(e).__name__,
            "mro": [c.__name__ for c in type(e).__mro__],
            "message": str(e)[:1000],
            "traceback": traceback.format_exc()[-2000:],
        }
    result["stdout"] = out.getvalue()[:4000]
    try:
        data = pickle.dumps(result)
    except Exception as e:  # 직렬화 불가 출력
        result.pop("outputs", None)
        result.update(ok=False, error={"type": "TypeError", "mro": ["TypeError"], "traceback": "",
                                       "message": f"출력을 직렬화할 수 없다: {e}"})
        data = pickle.dumps(result)
    # 가드가 쓰기를 작업 폴더 안으로 한정하므로 그대로 기록해도 된다
    with open(os.path.join(workdir, "result.pkl"), "wb") as f:
        f.write(data)


if __name__ == "__main__":
    main()
