"""단일 실행: 빌드된 화면을 API와 같은 포트로 서빙한다. HTTP 동작만 본다 (키·네트워크 없음)."""
from fastapi.testclient import TestClient

from jejuagent.api.app import create_app
from jejuagent.llm import FakeLLM


def make(web_dir, tmp_path):
    return TestClient(create_app(lambda: FakeLLM([]), runs_dir=tmp_path / "runs", web_dir=web_dir))


def web(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html>앱</html>", encoding="utf-8")
    (d / "assets" / "a.js").write_text("console.log(1)", encoding="utf-8")
    return d


def test_serves_index_and_assets(tmp_path):
    c = make(web(tmp_path), tmp_path)
    assert "앱" in c.get("/").text
    assert c.get("/assets/a.js").text == "console.log(1)"


def test_api_is_not_shadowed(tmp_path):
    c = make(web(tmp_path), tmp_path)
    assert c.get("/api/catalog").status_code == 200
    assert c.get("/api/nope").status_code == 404   # index.html 이 아님
    assert c.get("/api/runs/unknown").status_code == 404


def test_without_build_root_explains_and_api_works(tmp_path):
    c = make(tmp_path / "missing", tmp_path)
    assert "npm run build" in c.get("/").json()["message"]
    assert c.get("/api/catalog").status_code == 200
