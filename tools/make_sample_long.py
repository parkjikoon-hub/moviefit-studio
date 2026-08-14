"""긴 영상 점검용 30분짜리 시험 영상을 만든다.

    python tools/make_sample_long.py            # 30분
    python tools/make_sample_long.py --minutes 45

말소리가 든 짧은 영상(`tests/sample/sample_speech.mp4`)을 필요한 횟수만큼
이어 붙인다. **다시 인코딩하지 않으므로**(-c copy) 몇 초면 끝난다.

왜 색막대 영상(`sample_10s.mp4`)을 쓰지 않는가:
    그 영상에는 말소리가 없어서 음성인식이 자막을 하나도 못 만든다.
    그러면 "30분 영상에서 음성인식이 완료된다"를 확인할 수 없다.

만든 파일은 저장소에 넣지 않는다 (`.gitignore` 의 `tests/sample/*.mp4`).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tests" / "sample" / "sample_speech.mp4"
OUT = ROOT / "tests" / "sample" / "sample_30min.mp4"


def seconds_of(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="긴 영상 점검용 시험 영상 만들기")
    parser.add_argument("--minutes", type=float, default=30.0, help="몇 분짜리로 만들지 (기본 30)")
    parser.add_argument("--force", action="store_true", help="이미 있어도 다시 만든다")
    args = parser.parse_args()

    if not SOURCE.is_file():
        print(f"원본이 없습니다: {SOURCE}")
        print("  python tools/make_sample_speech.py 를 먼저 실행하세요 (인터넷 필요).")
        return 1

    if OUT.is_file() and not args.force:
        print(f"이미 있습니다: {OUT}  ({seconds_of(OUT) / 60:.1f}분)")
        print("  다시 만들려면 --force 를 붙이세요.")
        return 0

    unit = seconds_of(SOURCE)
    target = args.minutes * 60
    loops = int(target / unit) + 1  # 목표보다 살짝 길게

    print(f"원본 {unit:.1f}초짜리를 {loops}번 이어 붙여 약 {args.minutes:.0f}분을 만듭니다.")
    print("다시 인코딩하지 않으므로 금방 끝납니다...")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-stream_loop", str(loops - 1), "-i", str(SOURCE),
         "-c", "copy", str(OUT)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("만들지 못했습니다:")
        print(result.stderr[:500])
        return 1

    made = seconds_of(OUT)
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"만들었습니다: {OUT}")
    print(f"  길이 {made / 60:.1f}분 ({made:.1f}초) · {size_mb:.0f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
