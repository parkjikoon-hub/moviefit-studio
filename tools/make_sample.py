"""테스트용 샘플 파일 생성 — tests/sample/ 에 짧은 영상과 대본을 만든다.

개발·검증할 때 매번 진짜 영상을 찾지 않아도 되게 하는 용도다.
실행: python tools/make_sample.py
"""

from __future__ import annotations

import re
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

SCRIPT_TEXT = """안녕하세요. 무비핏 스튜디오 테스트 대본입니다.
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


NARR_DIR = SAMPLE_DIR / "narration"

# 샘플 나레이션에 쓸 목소리 (한국어 전용 3종)
SAMPLE_VOICES = [
    ("ko-KR-SunHiNeural", "선희_여성"),
    ("ko-KR-InJoonNeural", "인준_남성"),
    ("ko-KR-HyunsuMultilingualNeural", "현수_남성"),
]


def make_narration() -> int:
    """샘플 대본을 문장별 mp3로 만든다.

    나레이션 기능을 손으로 확인할 때 매번 인터넷으로 새로 만들지 않아도 되게 하는 용도다.
    파일 이름에 순번·목소리·문장 앞부분을 넣어 탐색기에서 바로 알아볼 수 있게 한다.
    """
    try:
        import asyncio

        import edge_tts
    except ImportError:
        print("  edge-tts가 없어 샘플 나레이션을 건너뜁니다.")
        return 0

    from app.core.ffprobe import ProbeError, measure_duration

    NARR_DIR.mkdir(parents=True, exist_ok=True)
    sentences = [s.strip() for s in SCRIPT_TEXT.splitlines() if s.strip()]

    async def synth(text: str, voice: str, path: Path) -> None:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(path))

    made = 0
    # 문장별 파일 — 기본 목소리(선희)로 전 문장
    for index, sentence in enumerate(sentences, start=1):
        head = re.sub(r"[^가-힣A-Za-z0-9]", "", sentence)[:10]
        path = NARR_DIR / f"나레이션_{index:02d}_선희_{head}.mp3"
        if path.exists():
            made += 1
            continue
        try:
            asyncio.run(synth(sentence, SAMPLE_VOICES[0][0], path))
        except Exception as exc:  # 인터넷이 없거나 경로가 막힌 경우
            print(f"  [건너뜀] 문장 {index} — {type(exc).__name__} (인터넷 연결을 확인하세요)")
            continue
        try:
            seconds = measure_duration(path)
            print(f"  [완료] {path.name}  ({seconds:.2f}초)")
        except ProbeError:
            print(f"  [완료] {path.name}")
        made += 1

    # 목소리 비교용 — 같은 문장을 세 목소리로
    compare_text = "안녕하세요. 무비핏 스튜디오 목소리 비교용 문장입니다."
    for voice_id, nickname in SAMPLE_VOICES:
        path = NARR_DIR / f"목소리비교_{nickname}.mp3"
        if path.exists():
            made += 1
            continue
        try:
            asyncio.run(synth(compare_text, voice_id, path))
            print(f"  [완료] {path.name}")
            made += 1
        except Exception as exc:
            print(f"  [건너뜀] {nickname} — {type(exc).__name__}")

    return made


def main() -> int:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    print("샘플 파일을 만듭니다…")
    ok = make_video()
    if ok:
        size_mb = SAMPLE_VIDEO.stat().st_size / 1024 / 1024
        print(f"  [완료] {SAMPLE_VIDEO}  ({size_mb:.1f} MB, 10초)")

    SAMPLE_SCRIPT.write_text(SCRIPT_TEXT, encoding="utf-8")
    print(f"  [완료] {SAMPLE_SCRIPT}  (문장 4개)")

    print("\n샘플 나레이션 음성을 만듭니다 (인터넷 필요)…")
    count = make_narration()
    print(f"  나레이션 파일 {count}개 준비됨 → {NARR_DIR}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
