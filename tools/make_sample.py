"""테스트용 샘플 파일 생성 — tests/sample/ 에 짧은 영상과 대본을 만든다.

개발·검증할 때 매번 진짜 영상을 찾지 않아도 되게 하는 용도다.
실행: python tools/make_sample.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import SAMPLE_DIR  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SAMPLE_VIDEO = SAMPLE_DIR / "sample_10s.mp4"
SAMPLE_SCRIPT = SAMPLE_DIR / "sample_script.txt"

SCRIPT_TEXT = """안녕하세요. 캡컷 스튜디오 테스트 대본입니다.
이 도구는 영상에서 자막을 자동으로 만들어 줍니다.
대본을 넣으면 나레이션 음성도 함께 만들어집니다.
자막과 음성의 타이밍은 자동으로 맞춰집니다.
"""


def make_video() -> bool:
    """색 막대 화면 + 사인파 소리로 10초짜리 mp4를 만든다."""
    if shutil.which("ffmpeg") is None:
        print("  FFmpeg이 없어 샘플 영상을 만들 수 없습니다. python tools/check_env.py 를 참고하세요.")
        return False

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-c:a", "aac", "-shortest",
        str(SAMPLE_VIDEO),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("  샘플 영상 생성 실패:")
        print("  " + (result.stderr or "").strip()[-500:])
        return False
    return True


def main() -> int:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    print("샘플 파일을 만듭니다…")
    ok = make_video()
    if ok:
        size_mb = SAMPLE_VIDEO.stat().st_size / 1024 / 1024
        print(f"  [완료] {SAMPLE_VIDEO}  ({size_mb:.1f} MB, 10초)")

    SAMPLE_SCRIPT.write_text(SCRIPT_TEXT, encoding="utf-8")
    print(f"  [완료] {SAMPLE_SCRIPT}  (문장 4개)")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
