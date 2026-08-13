"""말소리가 든 점검용 영상을 만든다 — 강제정렬(내 대본에 시간 붙이기) 점검용.

왜 필요한가:
`tests/sample/sample_10s.mp4` 는 색 막대 화면 + 사인파 소리다. **말소리가 없다.**
그래서 음성인식을 돌리면 자막이 0개 나오고, 강제정렬을 시험할 수 없다.

무엇을 만드나:
`tests/sample/sample_script.txt` 의 문장들을 나레이션으로 읽어 이어 붙이고,
그 소리를 색 막대 화면에 얹어 `tests/sample/sample_speech.mp4` 로 만든다.
**대본과 말소리가 정확히 같으므로** 강제정렬의 결과를 채점할 수 있다.

인터넷이 필요하다 (edge-tts 가 마이크로소프트 서버에서 음성을 받아온다).

사용법:
    python tools/make_sample_speech.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLE_DIR = ROOT / "tests" / "sample"
SCRIPT_FILE = SAMPLE_DIR / "sample_script.txt"
OUT_VIDEO = SAMPLE_DIR / "sample_speech.mp4"
VOICE = "ko-KR-SunHiNeural"
GAP_SECONDS = 0.45   # 문장 사이 정적. 너무 붙으면 어디서 끊겼는지 알기 어렵다.


def main() -> int:
    if shutil.which("ffmpeg") is None:
        print("FFmpeg 이 없습니다. python tools/check_env.py 를 참고하세요.")
        return 1
    if not SCRIPT_FILE.is_file():
        print(f"대본이 없습니다: {SCRIPT_FILE}")
        return 1

    try:
        import asyncio

        import edge_tts
    except ImportError:
        print("edge-tts 가 없습니다.  python -m pip install edge-tts")
        return 1

    sentences = [s.strip() for s in SCRIPT_FILE.read_text(encoding="utf-8").splitlines() if s.strip()]
    if not sentences:
        print("대본이 비어 있습니다.")
        return 1

    from app.core.audio_mix import trim_silence  # 앞뒤 무음을 잘라 시각을 또렷하게

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        parts: list[Path] = []

        async def synth(text: str, path: Path) -> None:
            await edge_tts.Communicate(text, VOICE).save(str(path))

        for index, text in enumerate(sentences):
            mp3 = work / f"s{index:03d}.mp3"
            print(f"  [{index + 1}/{len(sentences)}] 읽는 중: {text[:30]}…")
            try:
                asyncio.run(synth(text, mp3))
            except Exception as exc:  # noqa: BLE001
                print(f"음성을 받지 못했습니다 (인터넷 연결을 확인해 주세요): {exc}")
                return 1
            try:
                trim_silence(mp3)
            except Exception:
                pass  # 무음 제거에 실패해도 샘플로 쓰는 데는 지장이 없다
            parts.append(mp3)

        # 문장 사이에 정적을 끼워 이어 붙인다.
        silence = work / "gap.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", f"anullsrc=channel_layout=mono:sample_rate=24000:d={GAP_SECONDS}",
             "-c:a", "libmp3lame", str(silence)],
            check=True, timeout=120,
        )
        listing = work / "list.txt"
        lines = []
        for index, part in enumerate(parts):
            if index:
                lines.append(f"file '{silence.name}'")
            lines.append(f"file '{part.name}'")
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")

        speech = work / "speech.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", listing.name, "-c", "copy", str(speech)],
            check=True, cwd=str(work), timeout=180,
        )

        from app.core.ffprobe import measure_duration

        seconds = measure_duration(speech)
        SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error",
             "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=30:duration={seconds:.3f}",
             "-i", str(speech),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
             "-c:a", "aac", "-b:a", "128k", "-shortest",
             str(OUT_VIDEO)],
            check=True, timeout=300,
        )

    print(f"\n말소리가 든 샘플 영상을 만들었습니다 → {OUT_VIDEO}")
    print(f"  문장 {len(sentences)}개 · 길이 약 {seconds:.1f}초 · 목소리 {VOICE}")
    print("  대본은 tests/sample/sample_script.txt 와 정확히 같습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
