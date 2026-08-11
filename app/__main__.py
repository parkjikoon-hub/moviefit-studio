"""서버 실행 진입점.

사용법:
    python -m app              → 서버 기동
    python -m app --open       → 서버 기동 + 브라우저 자동 열기 (run.bat이 이걸 쓴다)
"""

from __future__ import annotations

import argparse
import logging
import threading
import time
import webbrowser

import sys

import uvicorn

from app.config import HOST, PORT

# 윈도우 한글 명령창의 기본 인코딩(cp949)은 '—' 같은 문자를 표현하지 못해
# 시작 메시지를 찍는 것만으로도 프로그램이 죽는다. 출력 인코딩을 UTF-8로 맞춘다.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def _open_browser_soon(url: str, delay: float = 1.5) -> None:
    """서버가 뜰 시간을 잠깐 준 뒤 기본 브라우저를 연다."""

    def worker() -> None:
        time.sleep(delay)
        webbrowser.open(url)

    threading.Thread(target=worker, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(description="CapCut Studio 로컬 서버")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--open", action="store_true", help="브라우저를 자동으로 연다")
    parser.add_argument("--reload", action="store_true", help="개발용: 코드 수정 시 자동 재시작")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")

    url = f"http://{args.host}:{args.port}"
    print("=" * 60)
    print("  CapCut Studio — 자막·나레이션 스튜디오")
    print(f"  주소: {url}")
    print("  이 창을 닫으면 프로그램이 종료됩니다.")
    print("=" * 60)

    if args.open:
        _open_browser_soon(url)

    uvicorn.run(
        "app.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
