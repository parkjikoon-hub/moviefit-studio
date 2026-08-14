"""사용설명서 자동 생성기 — 원본 하나(docs/USER_GUIDE.md)에서 HTML 두 개를 만든다.

같은 설명서가 세 곳에 필요하다.

    docs/USER_GUIDE.md      ← 원본. 사람이 고치는 곳은 여기 하나뿐이다.
    landing/guide.html      ← 소개 사이트(Vercel)에 올라가는 페이지
    app/static/guide.html   ← 프로그램 안에서 인터넷 없이 열리는 페이지

손으로 복사하면 반드시 어긋난다. 그래서 이 스크립트가 두 HTML을 **만들어 낸다.**
두 HTML은 자동 생성물이므로 직접 고치지 말고 원본 마크다운을 고친 뒤 다시 돌린다.

실행:
    python tools/build_guide.py           두 파일을 만든다
    python tools/build_guide.py --check   만들어질 내용과 지금 파일이 같은지만 본다
                                          (같으면 종료 코드 0, 다르면 1 — 점검용)

바깥 부품(pip으로 설치하는 것)을 쓰지 않는다. 설명서에 쓰는 마크다운 문법이 정해져 있어서
그만큼만 처리하면 되고, 설치 파일 크기에 영향을 주지 않기 위해서다.

지원하는 마크다운 문법 (설명서에서 실제로 쓰는 것만):
    ## 제목              → <h2 id="...">
    ### 소제목           → <h3>
    - 항목 / 1. 항목     → <ul><li> / <ol><li>
    | 표 | 머리 |         → <table>
    > 참고                → <p class="tip">   (여러 줄이면 하나로 합친다)
    **[단추이름]**        → <span class="ui">단추이름</span>
    **굵게**              → <b>
    `코드`                → <code>
    [글](주소)            → <a href="주소">
    <주소>                → <a href="주소">
    ---                   → 구역 나눔 (버린다)
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

# 윈도우 명령창은 cp949라 유니코드 기호에서 죽는다 (memory/windows-console-encoding.md)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "USER_GUIDE.md"
OUT_LANDING = ROOT / "landing" / "guide.html"
OUT_APP = ROOT / "app" / "static" / "guide.html"

# 장(章) 제목 → HTML 앵커 이름.
# 이미 밖으로 알려진 주소(/guide#tts 등)를 깨뜨리지 않으려고 기존 이름을 그대로 쓴다.
# 여기 없는 새 장은 sec<번호> 가 된다.
ANCHORS = {
    "이 프로그램은 무엇인가": "what",
    "설치하기": "install",
    "처음 켜기": "first",
    "영상에서 자막 만들기": "stt",
    "자막 고치기": "edit",
    "자막 모양 꾸미기": "style",
    "자막 위치 옮기기": "pos",
    "화면비 바꾸기 (가로·세로·정사각)": "aspect",
    "대본으로 나레이션 만들기": "tts",
    "자주 틀리는 단어를 사전에 등록하기": "dict",
    "결과물 내보내기": "export",
    "단축키": "keys",
    "문제가 생겼을 때": "trouble",
    "내 파일은 어디에 저장되나": "files",
    "자주 묻는 질문": "faq",
}

# 목차에 넣을 때는 짧게 줄여 쓰는 장이 있다 (두 줄로 넘어가면 목차가 지저분해진다)
TOC_SHORT = {
    "자주 틀리는 단어를 사전에 등록하기": "사전에 단어 등록하기",
    "화면비 바꾸기 (가로·세로·정사각)": "화면비 바꾸기 (가로·세로)",
}

# `**[X]**` 바로 뒤에 붙는 조사. 이럴 때만 사이의 빈칸을 없앤다.
# ("[스타일] 탭에서" 처럼 조사가 아닌 말이 오면 빈칸을 그대로 둔다)
PARTICLES = "를|을|이|가|은|는|로|으로|에|에서|와|과|의|도|만|까지|부터|라고|보다|처럼"


# ─── 한 줄 안쪽(인라인) 변환 ────────────────────────────────────────────────

def inline(text: str) -> str:
    """한 줄 안의 강조·코드·링크를 HTML로 바꾼다. 순서가 중요하다."""
    # 1) 코드(`...`)를 먼저 빼돌린다. 그 안의 * 나 [ 를 강조로 오해하면 안 되기 때문이다.
    stash: list[str] = []

    def _park(m: re.Match) -> str:
        stash.append("<code>" + html.escape(m.group(1)) + "</code>")
        return f"\x00{len(stash) - 1}\x00"

    text = re.sub(r"`([^`]+)`", _park, text)

    # 2) 나머지 글자를 HTML 안전하게 만든다
    text = html.escape(text)

    # 3) 링크 — [글](주소) 와 <주소> 두 가지
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )
    text = re.sub(r"&lt;(https?://[^&]+)&gt;", r'<a href="\1">\1</a>', text)

    # 4) **[단추이름]** → 화면에 있는 항목 표시. **굵게** 보다 먼저 처리해야 한다.
    text = re.sub(r"\*\*\[([^\]]+)\]\*\*", r'<span class="ui">\1</span>', text)
    # 5) **굵게**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)

    # 6) 항목 표시 뒤에 조사가 바로 오면 빈칸을 없앤다 ("[저장] 를" → "[저장]를")
    text = re.sub(
        rf"(</span>) ({PARTICLES})(?=[\s,.·)]|$)",
        r"\1\2",
        text,
    )

    # 7) 빼돌린 코드를 되돌린다
    for i, code in enumerate(stash):
        text = text.replace(f"\x00{i}\x00", code)
    return text


# ─── 문서 전체(블록) 변환 ──────────────────────────────────────────────────

def split_row(line: str) -> list[str]:
    """표의 한 줄을 칸으로 나눈다."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_separator(line: str) -> bool:
    """표의 머리와 몸통을 가르는 줄인가 (|---|---|)"""
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


def convert(md: str) -> tuple[list[tuple[str, str, str]], str]:
    """마크다운 본문을 HTML로 바꾼다.

    돌려주는 것: (목차용 [(앵커, 표시이름, 원래제목)] 목록, 본문 HTML)
    """
    lines = md.split("\n")
    out: list[str] = []
    toc: list[tuple[str, str, str]] = []
    i = 0
    chapter = 0

    # 앞머리(제목·버전·변경 이력·목차)는 건너뛴다. 첫 "## 1." 부터가 본문이다.
    while i < len(lines) and not re.match(r"^##\s+1\.\s", lines[i]):
        i += 1

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 빈 줄 · 구역 나눔
        if not stripped or stripped == "---":
            i += 1
            continue

        # ## 장 제목
        m = re.match(r"^##\s+(\d+)\.\s+(.*)$", stripped)
        if m:
            chapter = int(m.group(1))
            title = m.group(2).strip()
            anchor = ANCHORS.get(title, f"sec{chapter}")
            toc.append((anchor, TOC_SHORT.get(title, title), title))
            out.append(f"\n  <!-- {chapter} -->")
            out.append(f'  <h2 id="{anchor}">{chapter}. {inline(title)}</h2>')
            i += 1
            continue

        # ### 소제목
        m = re.match(r"^###\s+(.*)$", stripped)
        if m:
            out.append(f"  <h3>{inline(m.group(1).strip())}</h3>")
            i += 1
            continue

        # > 참고 상자 (이어지는 > 줄을 하나로 합친다)
        if stripped.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(f'  <p class="tip">{inline(" ".join(buf))}</p>')
            continue

        # | 표 |
        if stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not is_separator(lines[i]):
                    rows.append(split_row(lines[i]))
                i += 1
            if rows:
                out.append("  <table>")
                head, *body = rows
                out.append(
                    "    <tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>"
                )
                for row in body:
                    out.append(
                        "    <tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
                    )
                out.append("  </table>")
            continue

        # - 목록 / 1. 목록 (이어지는 줄은 같은 항목에 붙인다)
        m_ul = re.match(r"^[-*]\s+(.*)$", stripped)
        m_ol = re.match(r"^\d+\.\s+(.*)$", stripped)
        if m_ul or m_ol:
            tag = "ul" if m_ul else "ol"
            items: list[str] = []
            while i < len(lines):
                s = lines[i].strip()
                mm = re.match(r"^[-*]\s+(.*)$" if tag == "ul" else r"^\d+\.\s+(.*)$", s)
                if mm:
                    items.append(mm.group(1).strip())
                elif s and lines[i].startswith(("  ", "\t")) and items:
                    items[-1] += " " + s          # 여러 줄로 이어진 항목
                else:
                    break
                i += 1
            out.append(f"  <{tag}>")
            for it in items:
                out.append(f"    <li>{inline(it)}</li>")
            out.append(f"  </{tag}>")
            continue

        # 그 밖은 문단 (빈 줄이 나올 때까지 이어 붙인다)
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{2,3}\s|>|\||[-*]\s|\d+\.\s|---$)", lines[i].strip()
        ):
            buf.append(lines[i].strip())
            i += 1
        if buf:
            out.append(f"  <p>{inline(' '.join(buf))}</p>")

    return toc, "\n".join(out).strip("\n")


# ─── 두 가지 껍데기 ───────────────────────────────────────────────────────

def toc_html(toc: list[tuple[str, str, str]], indent: str = "    ") -> str:
    rows = [f'{indent}  <li><a href="#{a}">{html.escape(name)}</a></li>' for a, name, _ in toc]
    return "\n".join(rows)


def landing_page(toc, body, version: str) -> str:
    """소개 사이트(Vercel)용 — 위쪽 메뉴와 바닥글이 붙는다."""
    return f"""<!DOCTYPE html>
<!-- 이 파일은 tools/build_guide.py 가 docs/USER_GUIDE.md 에서 만들어 냅니다.
     직접 고치지 마세요. 고쳐도 다음 생성 때 지워집니다.
     설명서를 고치려면 docs/USER_GUIDE.md 를 고치고 `python tools/build_guide.py` 를 실행하세요. -->
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>사용설명서 — MovieFit Studio</title>
<meta name="description" content="MovieFit Studio 사용설명서. 설치부터 자막 만들기, 화면비 바꾸기, 나레이션 만들기, 내보내기까지 처음 쓰는 사람을 위한 상세 안내.">
<meta name="theme-color" content="#0D0C0B">
<link rel="icon" href="icons/favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="icons/icon-192.png">
<link rel="apple-touch-icon" href="icons/icon-192.png">
<meta property="og:type" content="article">
<meta property="og:locale" content="ko_KR">
<meta property="og:site_name" content="MovieFit Studio">
<meta property="og:title" content="사용설명서 — MovieFit Studio">
<meta property="og:description" content="설치부터 자막 만들기, 화면비 바꾸기, 나레이션 만들기, 내보내기까지 처음 쓰는 사람을 위한 상세 안내.">
<meta property="og:image" content="icons/icon-512.png">
<link rel="stylesheet" href="style.css">
</head>
<body>

<a class="skip" href="#main">본문으로 건너뛰기</a>

<header class="topbar">
  <div class="wrap">
    <a class="brand" href="/">
      <img src="icons/icon-192.png" alt="" width="28" height="28">
      <span>MovieFit Studio</span>
    </a>
    <nav aria-label="주요 메뉴">
      <a class="nav-hide" href="/#features">기능</a>
      <a href="/#install">설치 방법</a>
      <a href="/guide">사용설명서</a>
      <a href="https://github.com/parkjikoon-hub/moviefit-studio">GitHub</a>
    </nav>
  </div>
</header>

<main id="main" class="guide">

  <div class="guide-head">
    <p class="eyebrow">사용설명서</p>
    <h1>처음 쓰는 분을 위한 안내</h1>
    <p class="sub">설치부터 결과물을 뽑아내기까지, 화면에 보이는 순서 그대로 적었습니다.
      프로그램 버전 {version} 기준입니다.</p>
  </div>

  <nav class="toc" aria-label="목차">
    <h2>목차</h2>
    <ol>
{toc_html(toc)}
    </ol>
  </nav>

{body}

  <div class="guide-foot">
    <div class="btnrow" style="justify-content:flex-start">
      <a class="btn btn-primary" href="https://github.com/parkjikoon-hub/moviefit-studio/releases/latest/download/MovieFitStudio-Setup.exe">설치 파일 내려받기 (Windows)</a>
      <a class="btn btn-secondary" href="/">소개 페이지로</a>
    </div>
  </div>

</main>

<footer>
  <div class="wrap">
    <div class="footlinks">
      <a href="/">소개</a>
      <a href="/guide">사용설명서</a>
      <a href="https://github.com/parkjikoon-hub/moviefit-studio">GitHub</a>
      <a href="https://github.com/parkjikoon-hub/moviefit-studio/issues">문제 신고</a>
    </div>
    <p class="disclaimer">CapCut은 ByteDance의 상표이며 본 프로젝트와 관련이 없습니다. 본 프로젝트는 어떤 회사의 후원이나 승인도 받지 않은 독립 오픈소스 프로젝트입니다. MIT 라이선스로 공개되어 있습니다.</p>
  </div>
</footer>

</body>
</html>
"""


def app_page(toc, body, version: str) -> str:
    """프로그램 안에서 여는 것 — 인터넷 없이 열려야 하므로 바깥 주소를 쓰지 않는다.

    색은 style.css 의 :root 를 그대로 쓴다(색을 여기 베끼면 나중에 어긋난다).
    배치 규칙만 guide.css 에 따로 두었다.
    """
    return f"""<!DOCTYPE html>
<!-- 이 파일은 tools/build_guide.py 가 docs/USER_GUIDE.md 에서 만들어 냅니다.
     직접 고치지 마세요. 고쳐도 다음 생성 때 지워집니다. -->
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>사용설명서 — MovieFit Studio</title>
<link rel="icon" href="icons/favicon.ico" sizes="any">
<link rel="stylesheet" href="style.css">
<link rel="stylesheet" href="guide.css">
</head>
<body class="guide-page">

<header class="guide-bar">
  <span class="guide-bar-title">사용설명서</span>
  <span class="guide-bar-hint">이 탭을 닫으면 하던 작업으로 돌아갑니다.</span>
  <span class="guide-bar-ver">버전 {version}</span>
  <a class="guide-bar-link" href="#toc">목차</a>
  <a class="guide-bar-link" href="#top">↑ 맨 위로</a>
</header>

<main id="main" class="guide">

  <div class="guide-head" id="top">
    <h1>처음 쓰는 분을 위한 안내</h1>
    <p class="sub">설치부터 결과물을 뽑아내기까지, 화면에 보이는 순서 그대로 적었습니다.
      이 설명서는 프로그램 안에 들어 있어 인터넷 없이도 열립니다.</p>
  </div>

  <nav class="toc" id="toc" aria-label="목차">
    <h2>목차</h2>
    <ol>
{toc_html(toc)}
    </ol>
  </nav>

{body}

  <div class="guide-foot">
    <p>이 설명서는 프로그램 안에 들어 있습니다. 인터넷이 끊겨도 언제든 열립니다.</p>
    <a class="btn btn-primary" href="/">작업 화면 열기</a>
  </div>

</main>

</body>
</html>
"""


# ─── 실행 ────────────────────────────────────────────────────────────────

def read_version() -> str:
    """프로그램 버전은 app/__init__.py 하나에서만 읽는다 (두 곳에 적으면 어긋난다)."""
    text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    return m.group(1) if m else "0.0.0"


def main() -> int:
    check_only = "--check" in sys.argv

    if not SRC.exists():
        print(f"[실패] 원본을 찾을 수 없습니다: {SRC}")
        return 1

    version = read_version()
    toc, body = convert(SRC.read_text(encoding="utf-8"))

    targets = [
        (OUT_LANDING, landing_page(toc, body, version)),
        (OUT_APP, app_page(toc, body, version)),
    ]

    changed = []
    for path, content in targets:
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old == content:
            print(f"  그대로  {path.relative_to(ROOT)}")
            continue
        changed.append(path)
        if check_only:
            print(f"  다름!   {path.relative_to(ROOT)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"  새로 씀 {path.relative_to(ROOT)}  ({len(content):,}자)")

    print(f"\n원본: {SRC.relative_to(ROOT)}  ·  장 {len(toc)}개  ·  프로그램 버전 {version}")

    if check_only and changed:
        print("\n[다름] 만들어질 내용과 지금 파일이 다릅니다.")
        print("       `python tools/build_guide.py` 를 실행해 다시 만드세요.")
        return 1
    if not check_only:
        print("완료. 두 HTML은 자동 생성물이므로 직접 고치지 마세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
