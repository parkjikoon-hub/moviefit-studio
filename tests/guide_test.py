"""사용설명서 점검 — 설명서가 실제로 열리고, 새 기능이 적혀 있고, 세 곳이 어긋나지 않는지 본다.

사용법:
    1) 다른 창에서 서버를 켠다:  python -m app            (설치본이 8765를 쓰고 있으면 --port 8766)
    2) set MOVIEFIT_TEST_URL=http://127.0.0.1:8766        (8766으로 띄웠을 때만)
    3) python tests/guide_test.py

무엇을 확인하는가:
  1절  서버가 /guide.html 과 /guide.css 를 실제로 내보내는가 (파일이 있는지가 아니라)
  2절  새 기능 4건(F-A~F-D)이 설명서 본문에 적혀 있는가
  3절  프로그램 화면에서 설명서로 가는 길이 있는가 (첫 화면·작업 화면 두 곳)
  4절  목차의 모든 고리가 실제로 존재하는 자리를 가리키는가 (깨진 고리 없음)
  5절  세 곳(마크다운 원본·소개 사이트·프로그램 안)이 어긋나 있지 않은가
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [통과] {label}" + (f"  ({detail})" if detail else ""))
    else:
        failed += 1
        print(f"  [실패] {label}" + (f"  ({detail})" if detail else ""))
    return bool(condition)


def get(path: str) -> tuple[int, str, str]:
    """서버에서 받아 온다. (상태코드, 본문, 내용종류)"""
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, "", ""
    except Exception as e:  # 서버가 아예 안 떠 있는 경우
        print(f"  [실패] {path} 를 받아 오지 못했습니다: {e}")
        return 0, "", ""


print(f"겨냥한 서버: {BASE}\n")

# ── 1절. 서버가 설명서를 실제로 내보내는가 ────────────────────────────────
print("1절 · 서버가 설명서를 내보내는가")

status, guide, ctype = get("/guide.html")
check("/guide.html 이 200으로 열린다", status == 200, f"상태 {status}")
check("HTML로 내려온다", "html" in ctype.lower(), ctype)
check("본문이 비어 있지 않다", len(guide) > 5000, f"{len(guide):,}자")

status_css, css, _ = get("/guide.css")
check("/guide.css 가 200으로 열린다", status_css == 200, f"상태 {status_css}")
check(
    "설명서 스타일이 색을 직접 적지 않고 style.css 의 변수를 쓴다",
    css != "" and "var(--" in css and not re.search(r"#[0-9A-Fa-f]{6}", css),
    "색 코드를 직접 적으면 나중에 화면 색을 바꿀 때 여기만 옛 색으로 남는다",
)

# ── 2절. 새 기능 4건이 설명서에 적혀 있는가 ──────────────────────────────
print("\n2절 · 새 기능 4건(F-A~F-D)이 설명서에 있는가")

WANTED = {
    "F-A 화면비 전환": ["원본 그대로", "가로 16:9", "세로 9:16", "정사각 1:1"],
    "F-B 자막 위치 화살표": ["Shift", "5%", "1%"],
    "F-C 롱폼·숏폼 (잘라내기/여백)": ["잘라내기", "여백 채우기", "잘라낼 자리"],
    "F-D 저장됨 클릭": ["저장됨", "Ctrl", "바로 저장"],
    "①-2 프로그램 안 설명서": ["인터넷이 끊겨", "새 탭"],
}
for name, words in WANTED.items():
    missing = [w for w in words if w not in guide]
    check(f"{name}", not missing, "빠진 낱말: " + ", ".join(missing) if missing else "")

check(
    "화면비를 다룬 장이 따로 있다",
    'id="aspect"' in guide,
    "목차에서 바로 갈 수 있어야 한다",
)

# ── 3절. 프로그램 화면에서 설명서로 가는 길 ──────────────────────────────
print("\n3절 · 프로그램 화면에서 설명서로 가는 길")

status_idx, index, _ = get("/")
check("작업 화면(/)이 열린다", status_idx == 200, f"상태 {status_idx}")
check(
    "첫 화면 아래에 [사용설명서] 가 있다",
    'id="link-guide"' in index and "사용설명서" in index,
)
check(
    "작업 화면 위쪽에도 설명서 단추가 있다",
    'id="link-guide-top"' in index,
)
links = re.findall(r'id="link-guide[^"]*"[^>]*href="([^"]+)"', index)
check(
    "두 길 모두 프로그램 안의 설명서를 가리킨다 (바깥 사이트가 아니라)",
    len(links) == 2 and all(u == "/guide.html" for u in links),
    f"가리키는 곳: {links}",
)
check(
    "새 탭에서 열려 하던 작업을 잃지 않는다",
    index.count('id="link-guide') == 2
    and all(
        'target="_blank"' in m
        for m in re.findall(r"<a[^>]*id=\"link-guide[^\"]*\"[^>]*>", index)
    ),
)

# ── 4절. 목차의 고리가 전부 살아 있는가 ─────────────────────────────────
print("\n4절 · 목차의 고리가 전부 살아 있는가")

anchors = set(re.findall(r'<h2 id="([^"]+)"', guide))
targets = re.findall(r'<a href="#([^"]+)"', guide)
broken = sorted({t for t in targets if t not in anchors})
check(
    f"목차 {len(targets)}개가 모두 실제 자리를 가리킨다",
    not broken,
    "깨진 고리: " + ", ".join(broken) if broken else f"장 {len(anchors)}개",
)
check("장이 15개다 (화면비 장이 늘어난 뒤)", len(anchors) == 15, f"{len(anchors)}개")

# ── 5절. 세 곳이 어긋나 있지 않은가 ─────────────────────────────────────
print("\n5절 · 세 곳(원본·소개 사이트·프로그램 안)이 어긋나지 않는가")

r = subprocess.run(
    [sys.executable, str(ROOT / "tools" / "build_guide.py"), "--check"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
check(
    "원본 마크다운에서 다시 만들어도 지금 파일과 같다",
    r.returncode == 0,
    "다르면 `python tools/build_guide.py` 를 실행해야 한다",
)

landing = (ROOT / "landing" / "guide.html").read_text(encoding="utf-8")
app_file = (ROOT / "app" / "static" / "guide.html").read_text(encoding="utf-8")


def chapters(html: str) -> list[str]:
    return re.findall(r'<h2 id="[^"]+">([^<]+)</h2>', html)


check(
    "소개 사이트와 프로그램 안의 장 제목이 완전히 같다",
    chapters(landing) == chapters(app_file) and len(chapters(landing)) == 15,
    f"소개 {len(chapters(landing))}장 · 프로그램 {len(chapters(app_file))}장",
)
check(
    "서버가 내보낸 설명서가 저장소의 파일과 같다",
    guide.replace("\r\n", "\n").strip() == app_file.replace("\r\n", "\n").strip(),
    "다르면 서버가 옛 파일을 들고 있는 것이다",
)
check(
    "두 HTML에 '직접 고치지 마세요' 안내가 있다",
    "직접 고치지 마세요" in landing and "직접 고치지 마세요" in app_file,
)
check(
    "설명서에 적힌 프로그램 버전이 app/__init__.py 와 같다",
    (m := re.search(r'__version__\s*=\s*"([^"]+)"',
                    (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")))
    is not None
    and f"버전 {m.group(1)}" in app_file,
    "설명서 위쪽에 표시되는 버전",
)

print(f"\n{'=' * 46}\n결과: {passed}개 통과 · {failed}개 실패\n{'=' * 46}")
sys.exit(1 if failed else 0)
