"""라이브 호출 실패를 네 가지로 구분하고 사용자에게 보여줄 한국어 원인·해결 방법을 만든다."""
from __future__ import annotations

_MSG = {
    "no_key": ("API 키가 설정되지 않았습니다.", "프로젝트 루트의 .env 파일에 {env}=발급받은키 를 넣고 서버를 다시 시작하세요. (.env.example 참고)"),
    "bad_key": ("API 키가 거절되었습니다(인증 실패).", ".env의 {env} 값이 올바른지, 활용 신청이 승인되었는지, 키가 만료되지 않았는지 확인하세요."),
    "network": ("외부 서비스에 연결하지 못했습니다.", "인터넷 연결과 방화벽을 확인하고 잠시 뒤 다시 시도하세요. 서비스 점검 중일 수도 있습니다."),
    "quota": ("일일 호출 한도를 넘었습니다.", "내일 같은 수집 명령을 다시 실행하면 중단된 곳부터 이어받습니다. 한도 상향은 서비스 제공처에 신청하세요."),
}


class LiveError(Exception):
    """kind: no_key | bad_key | network | quota. str(e)에는 키가 들어가지 않는다."""

    def __init__(self, kind: str, env: str = "", detail: str = ""):
        cause, fix = _MSG[kind]
        self.kind, self.env, self.detail = kind, env, detail
        self.cause, self.fix = cause, fix.format(env=env)
        super().__init__(f"{self.cause} {self.fix}")

    def as_dict(self) -> dict:
        return {"kind": self.kind, "cause": self.cause, "fix": self.fix, "detail": self.detail}


def redact(text: str, *secrets: str) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text
