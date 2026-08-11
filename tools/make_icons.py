"""PWA 아이콘 생성기 — app/static/icons/ 에 앱 아이콘 PNG들을 그려서 저장한다.

디자인: 어두운 둥근 사각형 위에 청록색 재생 삼각형과 자막 두 줄.
CapCut을 비롯한 어떤 상용 앱의 아이콘도 참고하지 않은 순수 창작 도형이다.

실행: python tools/make_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import STATIC_DIR  # noqa: E402

ICON_DIR = STATIC_DIR / "icons"

BG = (23, 24, 28, 255)  # #17181C — UI_SPEC 4절 다크 배경
TEAL = (45, 212, 191, 255)  # #2DD4BF — 포인트 색
TEAL_DIM = (17, 94, 89, 255)  # 어두운 청록 (테두리용)
WHITE = (245, 247, 250, 255)  # #F5F7FA — 자막 첫 줄

SS = 4  # 4배 크게 그린 뒤 줄여서 계단현상을 없앤다 (수퍼샘플링)


def _draw_icon(size: int, padding_ratio: float = 0.0) -> Image.Image:
    """아이콘 한 장을 그린다.

    padding_ratio: 마스커블 아이콘용 여백 비율. 안드로이드가 아이콘을 동그라미 등으로
    잘라낼 수 있으므로, 그림을 안쪽으로 밀어 넣어 잘려도 괜찮게 만든다.
    """
    canvas = size * SS
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 배경 둥근 사각형
    d.rounded_rectangle([0, 0, canvas - 1, canvas - 1], radius=int(canvas * 0.22), fill=BG)

    # 그림 영역(여백 적용)
    pad = canvas * padding_ratio
    x0, y0 = pad, pad
    w = h = canvas - pad * 2

    def px(fx: float, fy: float) -> tuple[float, float]:
        """그림 영역 안의 비율 좌표(0~1)를 실제 픽셀로 바꾼다."""
        return (x0 + w * fx, y0 + h * fy)

    # 프레임(영상 화면을 뜻하는 얇은 청록 테두리)
    fx0, fy0 = px(0.17, 0.17)
    fx1, fy1 = px(0.83, 0.83)
    d.rounded_rectangle(
        [fx0, fy0, fx1, fy1],
        radius=int(w * 0.10),
        outline=TEAL_DIM,
        width=max(1, int(w * 0.030)),
    )

    # 재생 삼각형 (위쪽 가운데)
    tri = [px(0.415, 0.290), px(0.415, 0.470), px(0.585, 0.380)]
    d.polygon(tri, fill=TEAL)

    # 자막 두 줄 (아래쪽) — 이 앱의 핵심인 '자막'을 상징
    bar_h = h * 0.075
    r = bar_h / 2

    b1x0, b1y0 = px(0.265, 0.575)
    d.rounded_rectangle([b1x0, b1y0, b1x0 + w * 0.470, b1y0 + bar_h], radius=r, fill=WHITE)

    b2x0, b2y0 = px(0.265, 0.700)
    d.rounded_rectangle([b2x0, b2y0, b2x0 + w * 0.300, b2y0 + bar_h], radius=r, fill=TEAL)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    made: list[str] = []

    # 일반 아이콘 (브라우저 탭, 홈 화면, 설치 앱)
    for size in (16, 32, 180, 192, 512):
        img = _draw_icon(size)
        out = ICON_DIR / f"icon-{size}.png"
        img.save(out)
        made.append(out.name)

    # 마스커블 아이콘 (안드로이드가 모양대로 잘라내는 용도 — 안쪽 여백 필요)
    for size in (192, 512):
        img = _draw_icon(size, padding_ratio=0.14)
        out = ICON_DIR / f"maskable-{size}.png"
        img.save(out)
        made.append(out.name)

    # favicon.ico (여러 해상도를 한 파일에 담는다)
    ico = _draw_icon(64)
    ico.save(ICON_DIR / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    made.append("favicon.ico")

    print("생성한 아이콘 파일:")
    for name in made:
        print(f"  - {ICON_DIR / name}")


if __name__ == "__main__":
    main()
