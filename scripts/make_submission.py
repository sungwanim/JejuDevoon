"""제출용 zip 생성 + 비밀값 점검. 사용: python scripts/make_submission.py [--out 경로.zip]

기본 출력은 시스템 임시 폴더(프로젝트 안에 zip을 남기지 않는다). 점검에서 문제가 나오면 zip을 지우고 종료코드 1.
포함: backend frontend catalog snapshots docs data README.md DESIGN.md .env.example
제외: .env .venv .cache runs/ module_store/ node_modules __pycache__ .pytest_cache .git .scratch *.key *.pem *.pyc
"""
from __future__ import annotations

import argparse
import getpass
import re
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = "everyoneJeju-submission"
INCLUDE = ["backend", "frontend", "catalog", "snapshots", "docs", "data", "README.md", "DESIGN.md", ".env.example", "run.bat", "run-demo.bat"]
EXCLUDE_DIRS = {".git", ".venv", ".cache", "runs", "module_store", "node_modules", "__pycache__",
                ".pytest_cache", ".scratch", ".idea", ".vscode"}
EXCLUDE_SUFFIX = {".key", ".pem", ".pyc", ".pyo", ".pkl"}
FORBIDDEN_NAMES = {".env"}   # 이름이 .env 인 파일이 zip에 있으면 실패

DATA_NOTICE = """data/ 폴더의 원본 입력 이용조건 (제출 zip 생성 스크립트가 넣은 안내)

- (B080)공개DEM_*: 국토지리정보원 DEM 90m. 이용조건(공공누리 유형·출처 표기 문구) 미확인. 지점 고도 조회에만 사용.
- 제주특별자치도 서귀포시_감귤 생산 정보_20240513.csv: 제주 공공데이터. 공공누리 유형 미확인.
- 제주채소류재배현황.csv: 제주데이터허브. 이용조건 미확인.
- docs/schemas/*: 제주데이터허브·공공데이터포털 API 명세서(참고 자료). 농업기상 관측데이터는 공공누리 제4유형(변경금지)이라 현재 사용하지 않음.
- 농업기상 3종 명세(관측지점 상세정보, 상세 관측데이터 V4, 생장도일)도 현재 코드에서 호출하지 않음.
자세한 내용: docs/submission/data-spec.md
"""

# 비밀값 패턴. 테스트의 가짜 값은 "test-key"처럼 짧고 sk- 접두어가 없어 걸리지 않는다.
SECRET_PATTERNS = {
    "openai_key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "key_assignment": re.compile(r"(?i)\b(OPENAI_API_KEY|JEJU_HUB_PROJECT_KEY|DATA_GO_KR_SERVICE_KEY)\b[ \t]*[=:][ \t]*['\"]?[A-Za-z0-9%+/_.=-]{8,}"),
    "service_key_param": re.compile(r"(?i)service_?key=[A-Za-z0-9%+/=]{20,}"),
    "generic_secret": re.compile(r"(?i)(api[_-]?key|secret|token|passwd|password)\b[ \t]*[=:][ \t]*['\"][A-Za-z0-9+/=_-]{24,}['\"]"),
    "hub_url_with_key": re.compile(r"open\.jejudatahub\.net/api/proxy/[A-Za-z0-9]+/(?!\{)[A-Za-z0-9_-]{16,}"),
}
WARN_PATTERNS = {"email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "user_name": re.compile(re.escape(getpass.getuser()))}
TEXT_SUFFIX = {".py", ".md", ".txt", ".json", ".ts", ".tsx", ".js", ".css", ".html", ".j2", ".yml", ".yaml", ".toml",
               ".csv", ".example", ".cfg", ".ini", ""}


def collect() -> list[Path]:
    files = []
    for name in INCLUDE:
        p = ROOT / name
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file()
                      and not (set(f.relative_to(ROOT).parts[:-1]) & EXCLUDE_DIRS)
                      and f.suffix.lower() not in EXCLUDE_SUFFIX
                      and not (f.name.startswith(".env") and f.name != ".env.example")]
        else:
            print(f"경고: {name} 없음", file=sys.stderr)
    return sorted(files)


def scan(zpath: Path) -> tuple[list[str], list[str]]:
    """zip을 다시 열어 점검한다 (만든 결과물 기준). (실패 목록, 경고 목록)."""
    bad, warn = [], []
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            parts = info.filename.split("/")
            if parts[-1] in FORBIDDEN_NAMES or (parts[-1].startswith(".env") and parts[-1] != ".env.example"):
                bad.append(f"금지 파일: {info.filename}")
            if set(parts[:-1]) & EXCLUDE_DIRS:
                bad.append(f"금지 폴더: {info.filename}")
            if parts[-1].endswith(tuple(EXCLUDE_SUFFIX - {".pkl"})):
                bad.append(f"금지 확장자: {info.filename}")
            if Path(info.filename).suffix.lower() not in TEXT_SUFFIX or info.file_size > 5_000_000:
                continue
            text = z.read(info).decode("utf-8", errors="ignore")
            for label, pat in SECRET_PATTERNS.items():
                for m in pat.finditer(text):
                    bad.append(f"비밀값 의심({label}): {info.filename}: {m.group(0)[:6]}… (길이 {len(m.group(0))})")
            for label, pat in WARN_PATTERNS.items():
                if pat.search(text):
                    warn.append(f"{label}: {info.filename}")
    return bad, warn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "jeju-submission.zip"))
    out = Path(ap.parse_args().out).resolve()
    if ROOT in out.parents:
        print("프로젝트 폴더 안에는 zip을 만들 수 없습니다. --out 을 바깥 경로로 지정하세요.", file=sys.stderr)
        return 2
    files = collect()
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f"{TOP}/{f.relative_to(ROOT).as_posix()}")
        z.writestr(f"{TOP}/data/이용조건.txt", DATA_NOTICE)
    bad, warn = scan(out)
    print(f"파일 {len(files) + 1}개, {out.stat().st_size / 1e6:.1f}MB -> {out}")
    for w in sorted(set(warn)):
        print("경고(확인 필요):", w)
    if bad:
        out.unlink()
        print("\n점검 실패. zip을 삭제했습니다:")
        print("\n".join(f" - {b}" for b in bad))
        return 1
    print("비밀값 점검 통과 (.env 없음, 키 패턴 없음, 금지 폴더·확장자 없음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
