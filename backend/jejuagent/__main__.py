"""한 번에 실행: `python -m jejuagent` (backend/ 에서). 127.0.0.1 에서만 서버를 열고 브라우저를 띄운다.
화면은 frontend/dist(미리 빌드)를 같은 포트로 서빙한다. JEJU_LLM=fake 이면 키 없는 데모."""
import argparse
import socket
import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"   # 외부 접속 차단: 로컬 API에는 인증이 없다


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex((HOST, port)) == 0


def open_when_ready(url: str, port: int) -> None:
    for _ in range(100):
        if port_in_use(port):
            webbrowser.open(url)
            return
        time.sleep(0.1)


def main() -> None:
    ap = argparse.ArgumentParser(prog="jejuagent")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if port_in_use(a.port):
        raise SystemExit(f"포트 {a.port}번이 이미 사용 중입니다. 이미 실행 중이 아니라면 --port 로 다른 번호를 지정하세요.")
    url = f"http://{HOST}:{a.port}/"
    if not a.no_browser:
        threading.Thread(target=open_when_ready, args=(url, a.port), daemon=True).start()
    print(f"제주 공공데이터 분석 Agent: {url}  (종료: Ctrl+C)")
    uvicorn.run("jejuagent.api.main:app", host=HOST, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
