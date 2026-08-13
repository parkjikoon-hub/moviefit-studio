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
# 색을 적는 방법은 여러 가지다. `#RRGGBB` 만 찾으면 `#fff` 나 `rgb(...)` 로 적힌 것을
# 놓친다 (독립 검증에서 지적된 구멍).
# 색 이름은 `white-space` 같은 **속성 이름**과 헷갈리기 쉽다.
# 앞뒤에 글자나 붙임표가 없을 때만 색으로 센다.
COLOR_PATTERNS = re.compile(
    r"#[0-9A-Fa-f]{3,8}\b|\brgba?\s*\(|\bhsla?\s*\(|"
    r"(?<![-\w])(?:white|black|red|blue|green|gray|grey|silver|teal|navy|orange)(?![-\w])",
    re.I,
)
stray = COLOR_PATTERNS.findall(css)
check(
    "설명서 스타일이 색을 직접 적지 않고 style.css 의 변수를 쓴다",
    css != "" and "var(--" in css and not stray,
    "직접 적힌 색: " + ", ".join(stray[:5]) if stray else "색 코드 0건",
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


# ── 6절. 설명서가 "실제 프로그램"과 맞는가 ───────────────────────────────
#
# 5절까지는 설명서끼리만 비교한다. 그것만으로는 **설명서 전체가 현실과 어긋나도**
# 전부 통과한다. 여기서는 설명서에 적힌 것을 프로그램 코드와 직접 맞대 본다.
print("\n6절 · 설명서에 적힌 것이 실제 프로그램과 맞는가")

index_html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

# 6-1. 설명서가 부르는 단추 이름이 화면에 그 이름으로 실제로 있는가.
#      이름이 바뀌면 설명서는 없는 단추를 가리키게 된다.
BUTTONS = [
    "원본 그대로", "가로 16:9", "세로 9:16", "정사각 1:1",
    "잘라내기", "여백 채우기", "잘라낼 자리", "여백을 흐린 배경으로 채우기",
    "화면비 (롱폼 · 숏폼)", "저장됨", "사용설명서",
]
missing_in_ui = [b for b in BUTTONS if b not in index_html]
missing_in_guide = [b for b in BUTTONS if b not in guide]
check(
    f"설명서가 부르는 이름 {len(BUTTONS)}개가 실제 화면에 그대로 있다",
    not missing_in_ui,
    "화면에 없는 이름: " + ", ".join(missing_in_ui) if missing_in_ui else "",
)
check(
    "그 이름들이 설명서에도 빠짐없이 적혀 있다",
    not missing_in_guide,
    "설명서에 없는 이름: " + ", ".join(missing_in_guide) if missing_in_guide else "",
)

# 6-2. 설명서가 적은 숫자(1%, 5%)가 프로그램이 실제로 쓰는 값과 같은가.
#      글자만 검사하면 프로그램을 2%로 바꿔도 설명서 점검은 통과한다.
step = re.search(r"const\s+NUDGE_STEP\s*=\s*([\d.]+)\s*,\s*NUDGE_STEP_BIG\s*=\s*([\d.]+)", app_js)
check(
    "자막 위치 화살표의 1%·5% 가 app.js 의 실제 값과 같다",
    step is not None
    and f"**{step.group(1)}%**" in (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    and f"**{step.group(2)}%**" in (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8"),
    f"app.js = {step.group(1)}% / {step.group(2)}%" if step else "app.js 에서 값을 못 찾음",
)

# 6-3. 설명서가 든 화면비 예시(1280×720 → 세로 9:16 잘라내기 = 404×720)가 사실인가.
#      **기대값을 서버에 물어보면 안 된다** — 서버가 틀리면 기대값도 같이 틀려 통과한다.
#      그래서 숫자를 여기에 못박아 둔다.
import json
import urllib.parse

FRAMING_CASES = [
    # (원본 가로, 원본 세로, 화면비, 맞춤, 기대 가로, 기대 세로)
    (1280, 720, "9:16", "crop", 404, 720),
    (1280, 720, "9:16", "pad", 720, 1280),
    (1280, 720, "1:1", "crop", 720, 720),
]
for w, h, aspect, fit, ew, eh in FRAMING_CASES:
    q = urllib.parse.urlencode({"w": w, "h": h, "aspect": aspect, "fit": fit, "focus_x": 50})
    st, body, _ = get(f"/api/system/framing?{q}")
    got = json.loads(body) if st == 200 and body else {}
    check(
        f"{w}×{h} → {aspect} {fit} = {ew}×{eh}",
        got.get("width") == ew and got.get("height") == eh,
        f"실제 {got.get('width')}×{got.get('height')}",
    )

# 6-4. 원본 마크다운의 본문이 하나도 빠지지 않고 HTML로 옮겨졌는가.
#      `--check` 만으로는 알 수 없다 — 생성기가 한 장을 통째로 삼켜도
#      두 HTML이 똑같이 삼키므로 언제나 통과하기 때문이다 (동어반복).
md = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
body_start = md.index("## 1. ")
plain = re.sub(r"<[^>]+>", "", app_file)      # HTML에서 태그를 걷어낸 글자
plain = plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
# 대괄호는 원본에서는 단추 표시로 쓰고 HTML에서는 상자 모양으로 바뀌므로 양쪽 다 없앤다
plain = plain.replace("[", "").replace("]", "")
plain = re.sub(r"\s+", "", plain)             # 빈칸을 모두 없애고 비교한다

lost = []
for line in md[body_start:].split("\n"):
    s = line.strip()
    if not s or s.startswith(("#", "|", ">", "-", "*", "---")) or re.match(r"^\d+\.", s):
        continue
    # 마크다운 표시를 걷어낸 뒤 앞부분이 HTML 안에 있는지 본다.
    # 단추 이름 `**[X]** 를` 은 HTML에서 `<span>X</span>를` 가 되어 빈칸이 사라지므로
    # 양쪽 모두에서 빈칸을 없애고 비교한다.
    t = re.sub(r"\]\([^)]*\)", "", s)          # [글](주소) → 글
    t = re.sub(r"<(https?://[^>]+)>", r"\1", t)  # <주소> → 주소
    t = t.replace("**", "").replace("`", "").replace("[", "").replace("]", "")
    t = re.sub(r"\s+", "", t)
    if len(t) >= 20 and t[:20] not in plain:
        lost.append(t[:40])
check(
    "원본 마크다운의 문단이 하나도 빠지지 않고 설명서에 들어갔다",
    not lost,
    "빠진 문단: " + " / ".join(lost[:3]) if lost else "전수 대조 통과",
)

# 6-5. 장 제목만 남고 본문이 비어 버리는 일이 없는가.
sections = re.split(r'<h2 id="[^"]+">', app_file)[1:]
thin = [s.split("</h2>")[0] for s in sections if len(re.sub(r"<[^>]+>", "", s)) < 200]
check(
    "모든 장에 본문이 들어 있다 (제목만 남은 장이 없다)",
    not thin,
    "본문이 너무 짧은 장: " + ", ".join(thin) if thin else f"{len(sections)}개 장 모두 정상",
)

# 6-6. 두 HTML의 **본문**이 같은가. 제목만 비교하면 본문이 갈라져도 못 잡는다.
def body_text(html: str) -> str:
    """설명서 **본문**만 뽑는다. 위아래 껍데기(메뉴·내려받기 단추)는 두 곳이 서로 다르다."""
    inner = html[html.index("<h2 id="):html.index('<div class="guide-foot">')]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", inner)).strip()

check(
    "소개 사이트와 프로그램 안의 본문 글자가 완전히 같다",
    body_text(landing) == body_text(app_file),
    f"소개 {len(body_text(landing)):,}자 · 프로그램 {len(body_text(app_file)):,}자",
)

print(f"\n{'=' * 46}\n결과: {passed}개 통과 · {failed}개 실패\n{'=' * 46}")
sys.exit(1 if failed else 0)
