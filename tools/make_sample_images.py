"""점검용 사진을 만든다 — 크기와 형식이 제각각이고, 장마다 색이 다르다.

왜 이런 도구가 필요한가:
사진 영상에서 가장 위험한 결함은 **오류 없이 틀린 영상이 나오는 것**이다.
크기가 다른 사진을 그냥 이어붙이면 FFmpeg 이 종료 코드 0으로 끝나면서
"마지막 사진만 되풀이되는 영상"을 내놓는다 (docs/RESEARCH 2.1절 실측).

이것을 잡으려면 **장마다 색이 다른** 사진이 있어야 한다. 만들어진 영상의
특정 시각에서 화면 색을 재어 "그때 몇 번째 사진이 나와야 하는가"와 맞대 보면
조용한 실패가 드러난다. 같은 색 사진으로는 절대 잡히지 않는다.

사용법:
    python tools/make_sample_images.py            → tests/sample/images 에 30장
    python tools/make_sample_images.py --count 5  → 5장만
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
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "tests" / "sample" / "images"

# 크기를 일부러 뒤섞는다. 가로 사진, 세로 사진, 정사각, 아주 작은 것까지.
SIZES = [
    (1920, 1080), (800, 1200), (640, 480), (1080, 1080), (1600, 900),
    (480, 800), (2000, 1000), (720, 1280), (1024, 768), (360, 640),
]
# 형식도 섞는다. jpg 만으로 시험하면 해독기 문제(2.1절)가 드러나지 않는다.
FORMATS = ["jpg", "png", "webp"]


def color_for(index: int) -> tuple[int, int, int]:
    """장마다 확실히 구별되는 색. 이웃한 장끼리 색이 크게 벌어지도록 고른다.

    빨강 계열만 30가지로 나누면 jpeg 압축 오차와 섞여 구별이 어렵다.
    그래서 세 채널을 서로 다른 주기로 돌린다.
    """
    r = (index * 97) % 256
    g = (index * 53 + 80) % 256
    b = (index * 149 + 160) % 256
    # 너무 어두우면 압축 뒤 구별이 어렵다. 최소 40 이상으로 올린다.
    return (max(40, r), max(40, g), max(40, b))


def make_one(path: Path, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    """한 가지 색으로 꽉 찬 사진 한 장을 만든다."""
    color = "0x%02X%02X%02X" % rgb
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}",
        "-frames:v", "1", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--out", type=str, default=str(OUT_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    made = []
    for i in range(args.count):
        width, height = SIZES[i % len(SIZES)]
        ext = FORMATS[i % len(FORMATS)]
        rgb = color_for(i)
        path = out_dir / f"{i + 1:03d}_{width}x{height}.{ext}"
        make_one(path, width, height, rgb)
        made.append((path.name, width, height, rgb))

    print(f"사진 {len(made)}장을 만들었습니다 → {out_dir}")
    for name, w, h, rgb in made[:5]:
        print(f"  {name}  {w}x{h}  RGB{rgb}")
    if len(made) > 5:
        print(f"  … 그 밖에 {len(made) - 5}장")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
