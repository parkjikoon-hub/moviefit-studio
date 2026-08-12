"""PWA 아이콘 생성기 — app/static/icons/ 에 앱 아이콘 PNG들을 그려서 저장한다.

디자인: 따뜻한 검정 둥근 사각형 위에 크림색 재생 삼각형과 자막 두 줄.
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

# 색은 화면(style.css)의 값을 그대로 따른다. 2026-08-12 개편으로 청록을 전부 버리고
# 크림 한 가지로 통일했는데, 아이콘만 청록으로 남아 화면과 따로 놀았다.
BG = (36, 33, 30, 255)  # #24211E — 화면의 '박스' 바탕(--bg-2). 순검정보다 조금 밝아야
#                          어두운 바탕화면에서도 아이콘 모양이 사각형으로 읽힌다.
CREAM = (232, 226, 213, 255)  # #E8E2D5 — 강조색(--cream). 재생 삼각형·자막 첫 줄
CREAM_DIM = (142, 133, 120, 255)  # #8E8578 — 한 단계 낮춘 크림(--line-cream).
#                                    테두리와 자막 둘째 줄에 써서 두 겹으로 보이게 한다.

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

    # 프레임(영상 화면을 뜻하는 얇은 테두리)
    fx0, fy0 = px(0.17, 0.17)
    fx1, fy1 = px(0.83, 0.83)
    d.rounded_rectangle(
        [fx0, fy0, fx1, fy1],
        radius=int(w * 0.10),
        outline=CREAM_DIM,
        width=max(1, int(w * 0.030)),
    )

    # 재생 삼각형 (위쪽 가운데)
    tri = [px(0.415, 0.290), px(0.415, 0.470), px(0.585, 0.380)]
    d.polygon(tri, fill=CREAM)

    # 자막 두 줄 (아래쪽) — 이 앱의 핵심인 '자막'을 상징
    bar_h = h * 0.075
    r = bar_h / 2

    b1x0, b1y0 = px(0.265, 0.575)
    d.rounded_rectangle([b1x0, b1y0, b1x0 + w * 0.470, b1y0 + bar_h], radius=r, fill=CREAM)

    b2x0, b2y0 = px(0.265, 0.700)
    d.rounded_rectangle([b2x0, b2y0, b2x0 + w * 0.300, b2y0 + bar_h], radius=r, fill=CREAM_DIM)

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
