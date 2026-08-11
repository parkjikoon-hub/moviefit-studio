"""한글 폰트 내려받기 — assets/fonts/ 에 Pretendard를 저장한다.

왜 필요한가: 자막을 영상에 새겨 넣을 때(번인) FFmpeg이 한글 폰트를 못 찾으면
글자가 전부 네모(□□□)로 나온다. 프로그램과 함께 폰트를 들고 다니면 이 문제가 없다.

Pretendard는 SIL Open Font License 1.1로 배포되어 재배포가 허용된다.
실행: python tools/fetch_font.py
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import FONTS_DIR  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://github.com/orioncactus/pretendard/raw/main/packages/pretendard/dist/public/static"
FONTS = {
    "Pretendard-Regular.otf": f"{BASE}/Pretendard-Regular.otf",
    "Pretendard-Bold.otf": f"{BASE}/Pretendard-Bold.otf",
}

LICENSE_NOTE = """이 폴더의 폰트는 Pretendard입니다.

- 이름: Pretendard
- 만든 사람: 길형진 (orioncactus)
- 라이선스: SIL Open Font License 1.1 (재배포·임베딩 허용)
- 원본: https://github.com/orioncactus/pretendard

CapCut Studio는 자막을 영상에 새겨 넣을 때 이 폰트를 사용합니다.
"""


def download(name: str, url: str) -> bool:
    target = FONTS_DIR / name
    if target.exists() and target.stat().st_size > 100_000:
        print(f"  [건너뜀] {name} — 이미 있습니다")
        return True

    print(f"  받는 중… {name}")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "capcut-studio/0.1"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"  [실패] {name} — {exc}")
        return False

    if len(data) < 100_000:  # 폰트치고 너무 작으면 오류 페이지를 받은 것이다
        print(f"  [실패] {name} — 받은 파일이 너무 작습니다 ({len(data)} 바이트)")
        return False

    target.write_bytes(data)
    print(f"  [완료] {target}  ({len(data) / 1024 / 1024:.1f} MB)")
    return True


def main() -> int:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    print("한글 자막용 폰트를 준비합니다 (인터넷 연결 필요)…")

    results = [download(name, url) for name, url in FONTS.items()]

    if any(results):
        (FONTS_DIR / "LICENSE.txt").write_text(LICENSE_NOTE, encoding="utf-8")

    if all(results):
        print("\n폰트 준비가 끝났습니다.")
        return 0

    print(
        "\n일부 폰트를 받지 못했습니다. 인터넷 없이 쓰려면 아래처럼 하세요.\n"
        "  1) https://github.com/orioncactus/pretendard/releases 에 접속\n"
        "  2) 최신 Pretendard 압축 파일을 내려받아 풉니다\n"
        f"  3) 그 안의 Pretendard-Regular.otf 를 {FONTS_DIR} 폴더에 복사합니다"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
