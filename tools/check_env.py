"""환경 점검 — 프로그램이 돌아가는 데 필요한 것들이 다 있는지 확인하고,
없으면 비개발자도 따라 할 수 있는 설치 방법을 한국어로 알려준다.

실행: python tools/check_env.py
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

# 윈도우 명령창에서 한글이 깨지지 않게 출력 인코딩을 맞춘다
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = "[정상]"
NG = "[없음]"
WARN = "[확인]"

problems: list[str] = []


def say(mark: str, title: str, detail: str = "") -> None:
    line = f"  {mark} {title}"
    if detail:
        line += f"  —  {detail}"
    print(line)


def check_python() -> None:
    v = sys.version_info
    if (v.major, v.minor) >= (3, 11):
        say(OK, "파이썬", f"{v.major}.{v.minor}.{v.micro}")
    else:
        say(NG, "파이썬", f"현재 {v.major}.{v.minor} — 3.11 이상이 필요합니다")
        problems.append(
            "◆ 파이썬 3.11 이상 설치\n"
            "   1) https://www.python.org/downloads/ 에서 최신 버전을 받습니다.\n"
            "   2) 설치 화면 맨 아래 'Add python.exe to PATH'를 반드시 체크합니다.\n"
            "   3) 설치가 끝나면 이 창을 닫고 다시 실행합니다."
        )


def check_ffmpeg() -> None:
    for name, label in (("ffmpeg", "FFmpeg (영상 처리)"), ("ffprobe", "ffprobe (길이 측정)")):
        path = shutil.which(name)
        if not path:
            say(NG, label)
            problems.append(
                "◆ FFmpeg 설치 (영상·오디오를 다루는 필수 도구)\n"
                "   가장 쉬운 방법 — 시작 메뉴에서 'PowerShell'을 열고 아래 한 줄을 붙여넣습니다.\n"
                "       winget install Gyan.FFmpeg\n"
                "   설치 후에는 열려 있던 명령창을 모두 닫고 다시 실행해야 인식됩니다."
            )
            return
        try:
            out = subprocess.run(
                [name, "-version"], capture_output=True, text=True, timeout=15
            ).stdout.splitlines()[0]
            version = out.split(" version ")[1].split()[0] if " version " in out else "설치됨"
        except (OSError, subprocess.TimeoutExpired, IndexError):
            version = "설치됨"
        say(OK, label, version)


def check_packages() -> None:
    required = {
        "fastapi": "웹 서버",
        "uvicorn": "서버 실행기",
        "pysubs2": "자막 파일 처리",
        "edge_tts": "AI 나레이션",
        "faster_whisper": "음성 인식",
        "PIL": "아이콘 생성 (Pillow)",
    }
    missing: list[str] = []
    for module, purpose in required.items():
        if importlib.util.find_spec(module) is None:
            say(NG, f"{module} ({purpose})")
            missing.append(module)
        else:
            say(OK, f"{module} ({purpose})")

    if missing:
        problems.append(
            "◆ 파이썬 패키지 설치\n"
            "   프로젝트 폴더에서 명령창을 열고 아래 한 줄을 붙여넣습니다.\n"
            "       python -m pip install -r requirements.txt"
        )


def check_assets() -> None:
    from app.config import FONTS_DIR, PROJECTS_DIR, SAMPLE_DIR

    fonts = list(FONTS_DIR.glob("*.ttf")) + list(FONTS_DIR.glob("*.otf")) if FONTS_DIR.exists() else []
    if fonts:
        say(OK, "번들 한글 폰트", f"{len(fonts)}개 ({fonts[0].name} 등)")
    else:
        say(WARN, "번들 한글 폰트", "없음 — 자막 번인 시 윈도우 기본 폰트를 씁니다")
        problems.append(
            "◆ 한글 폰트 준비 (선택)\n"
            "   자막을 영상에 새겨 넣을 때 글자가 깨지지 않게 하려면 아래를 실행합니다.\n"
            "       python tools/fetch_font.py"
        )

    samples = list(SAMPLE_DIR.glob("*.mp4")) if SAMPLE_DIR.exists() else []
    if samples:
        say(OK, "테스트용 샘플 영상", samples[0].name)
    else:
        say(WARN, "테스트용 샘플 영상", "없음 — python tools/make_sample.py 로 만들 수 있습니다")

    say(OK, "프로젝트 저장 폴더", str(PROJECTS_DIR))


def main() -> int:
    print()
    print("=" * 66)
    print("  MovieFit Studio 환경 점검")
    print("=" * 66)

    print("\n[1] 파이썬")
    check_python()

    print("\n[2] 영상 처리 도구")
    check_ffmpeg()

    print("\n[3] 파이썬 패키지")
    check_packages()

    print("\n[4] 부가 자료")
    try:
        check_assets()
    except Exception as exc:  # 설정 파일을 못 읽는 예외 상황
        say(WARN, "부가 자료 점검 실패", str(exc))

    print()
    print("=" * 66)
    if problems:
        print("  아래 항목을 처리하면 프로그램을 쓸 수 있습니다.\n")
        for item in problems:
            print(item)
            print()
        print("=" * 66)
        return 1

    print("  모든 항목이 정상입니다. run.bat 을 더블클릭해서 시작하세요.")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
