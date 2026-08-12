"""실행 담당 — run.bat이 부르는 파이썬 진입점.

한글 안내 문구가 여기에 있는 이유: 윈도우 배치 파일(.bat)은 한글을 제대로 읽지 못해
안내 문구가 깨진다. 그래서 배치 파일은 영문만 두고, 사용자에게 보여줄 말은 전부 여기서 찍는다.

하는 일:
  1) 필요한 패키지가 있는지 확인하고 없으면 자동 설치
  2) 한글 폰트가 없으면 자동으로 내려받는다
  3) 서버를 켜고 브라우저를 연다
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REQUIRED = {
    "fastapi": "웹 서버",
    "uvicorn": "서버 실행기",
    "pysubs2": "자막 파일 처리",
    "edge_tts": "AI 나레이션",
    "faster_whisper": "음성 인식",
}


def banner() -> None:
    print()
    print("=" * 60)
    print("  MovieFit Studio — 자막·나레이션 스튜디오")
    print("=" * 60)
    print()


def ensure_packages() -> bool:
    """빠진 패키지가 있으면 설치한다. 성공하면 True."""
    missing = [name for name in REQUIRED if importlib.util.find_spec(name) is None]
    if not missing:
        return True

    print("  처음 실행이라 필요한 부품을 설치합니다. 몇 분 걸릴 수 있습니다.")
    for name in missing:
        print(f"    · {name} ({REQUIRED[name]})")
    print()

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")]
    )
    if result.returncode != 0:
        print()
        print("  [오류] 부품 설치에 실패했습니다.")
        print("  인터넷 연결을 확인한 뒤 run.bat 을 다시 실행해 주세요.")
        print("  그래도 안 되면 이 창에 아래 한 줄을 붙여넣고 엔터를 눌러 보세요.")
        print(f"      {Path(sys.executable).name} -m pip install -r requirements.txt")
        return False

    print()
    return True


def ensure_fonts() -> None:
    """한글 폰트가 없으면 내려받는다.

    저장소에는 용량 때문에 폰트를 넣지 않는다(.gitignore). 그래서 GitHub에서 내려받은
    사람은 폰트가 없는 채로 시작하는데, 그러면 자막을 영상에 새길 때 화면 미리보기와
    글꼴이 달라진다. 첫 실행 때 자동으로 받아 두면 그 차이가 없어진다.

    인터넷이 없어도 프로그램은 계속 쓸 수 있어야 하므로, 실패하면 안내만 하고 넘어간다.
    """
    from app.config import FONTS_DIR, STATIC_DIR

    burn_ok = any(FONTS_DIR.glob("*.otf")) or any(FONTS_DIR.glob("*.ttf"))
    web_ok = any((STATIC_DIR / "fonts").glob("*.woff2"))
    if burn_ok and web_ok:
        return

    print("  한글 글꼴을 준비합니다 (처음 한 번, 약 3MB)…")
    try:
        from tools import fetch_font
    except ImportError:  # tools를 패키지로 못 읽는 경우
        import fetch_font  # type: ignore[no-redef]

    try:
        code = fetch_font.main()
    except Exception:  # 네트워크 오류 등 — 여기서 프로그램을 멈추지 않는다
        code = 1

    if code != 0:
        print("  [주의] 글꼴을 받지 못했습니다. 프로그램은 그대로 쓸 수 있지만,")
        print("         자막을 영상에 새길 때 글꼴이 화면 미리보기와 달라질 수 있습니다.")
        print("         인터넷 연결 후  python tools/fetch_font.py  를 실행하면 해결됩니다.")
    print()


def check_ffmpeg() -> None:
    """FFmpeg이 없으면 경고만 하고 계속 진행한다 (자막 편집까지는 쓸 수 있으므로)."""
    import shutil

    if shutil.which("ffmpeg") is None:
        print("  [주의] FFmpeg(영상 처리 도구)이 없습니다.")
        print("         자막 편집은 되지만, 영상 내보내기와 자막 자동 생성은 동작하지 않습니다.")
        print("         설치 방법: PowerShell을 열고  winget install Gyan.FFmpeg  를 실행")
        print()


def main() -> int:
    banner()

    if not ensure_packages():
        return 1
    ensure_fonts()
    check_ffmpeg()

    from app.config import HOST, PORT

    print(f"  주소: http://{HOST}:{PORT}")
    print("  잠시 후 브라우저가 자동으로 열립니다.")
    print("  ※ 이 검은 창을 닫으면 프로그램이 종료됩니다.")
    print()

    # 서버 실행은 app/__main__.py에 맡긴다 (개발용 실행 경로와 동일하게 유지)
    return subprocess.call([sys.executable, "-m", "app", "--open"], cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
