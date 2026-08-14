"""단축키 점검 — UI_SPEC 3절의 단축키를 진짜 브라우저에서 눌러 본다.

`docs/ROADMAP.md` Phase 5 수용 기준:
    "UI_SPEC 3절의 단축키가 모두 동작한다"

코드에 `e.key === " "` 가 있다고 해서 동작한다고 말하면 안 된다. 실제로 눌렀을 때
화면이 반응해야 한다 (memory/verify-ui-by-actually-clicking.md).

사용법:
    1) 서버를 띄운다        python -m app --port 8766
    2) 시험용 영상을 만든다  python tools/make_sample.py
    3) playwright 설치      python -m pip install playwright
                            python -m playwright install chromium
    4) 이 파일을 실행한다    set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
                            python tests/shortcuts_test.py

UI_SPEC 3절이 약속한 것 (이 파일이 전부 확인한다):
    Space        재생/일시정지 (텍스트 편집 중 아닐 때)
    ←/→          1초 이동, Shift 를 함께 누르면 0.1초
    ↑/↓          이전/다음 자막 선택
    Enter        선택한 자막 편집 시작
    Ctrl+Enter   (편집 중) 커서 자리에서 자막 나누기
    Ctrl+Z / Y   되돌리기 / 다시 실행
    Ctrl+F       자막 검색창으로 이동
    Ctrl+S       기다리지 않고 즉시 저장
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
SAMPLE = ROOT / "tests" / "sample" / "sample_10s.mp4"

passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    print(f"[{'  OK  ' if ok else ' FAIL '}] {name}" + (f"   — {detail}" if detail else ""))
    return ok


def api(path: str, method: str = "GET", body: dict | None = None):
    url = BASE + urllib.parse.quote(path, safe="/?&=.:%-")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as res:
        raw = res.read().decode("utf-8")
    return json.loads(raw) if raw else None


def dismiss_coach(page) -> None:
    """처음 열면 뜨는 안내 창을 닫는다 (열려 있으면 키가 먹지 않는다)."""
    for sel in ("#coach", "#shortcuts"):
        box = page.locator(sel)
        if box.count() and box.is_visible():
            close = page.locator(f"{sel} button.btn-primary, {sel}-close")
            if close.count():
                close.first.click()
            else:
                page.evaluate(f"document.querySelector('{sel}').hidden = true")
            page.wait_for_timeout(150)


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright 가 설치되어 있지 않습니다.")
    print("  python -m pip install playwright")
    print("  python -m playwright install chromium")
    sys.exit(2)

if not SAMPLE.is_file():
    print(f"샘플 영상이 없습니다: {SAMPLE}")
    print("  python tools/make_sample.py 를 먼저 실행하세요.")
    sys.exit(1)

project = api("/api/projects", "POST",
              {"name": "단축키점검", "video_path": str(SAMPLE), "mode": "video"})
pid = project["id"]
project["segments"] = [
    {"id": "s1", "start": 0.2, "end": 2.0, "text": "첫째 자막 문장입니다"},
    {"id": "s2", "start": 2.2, "end": 4.0, "text": "둘째 자막 문장입니다"},
    {"id": "s3", "start": 4.2, "end": 6.0, "text": "셋째 자막 문장입니다"},
]
api(f"/api/projects/{pid}", "PUT", project)
print(f"점검용 프로젝트: {pid}\n")

print("=" * 70)
print("  단축키 점검 — UI_SPEC 3절")
print("=" * 70)
print(f"  서버: {BASE}\n")

try:
    with sync_playwright() as pw:
        # 소리 재생을 사용자 클릭 없이도 허용해야 Space(재생) 를 검사할 수 있다
        browser = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page(viewport={"width": 1600, "height": 950})

        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"{BASE}/?project={pid}", wait_until="networkidle")
        dismiss_coach(page)
        page.wait_for_function("document.querySelector('#player').videoWidth > 0", timeout=20000)
        page.wait_for_timeout(400)

        def seg_count() -> int:
            return page.evaluate("document.querySelectorAll('.seg-item').length")

        def active_id() -> str:
            return page.evaluate(
                "(document.querySelector('.seg-item.is-active')||{dataset:{}}).dataset.id || ''"
            )

        def current_time() -> float:
            return page.evaluate("document.querySelector('#player').currentTime")

        def is_paused() -> bool:
            return page.evaluate("document.querySelector('#player').paused")

        def blur() -> None:
            page.evaluate("document.activeElement && document.activeElement.blur()")

        # ══ Space — 재생/일시정지 ═══════════════════════════
        print("=== Space — 재생 / 일시정지 ===")
        blur()
        check("처음에는 멈춰 있다", is_paused() is True)
        page.keyboard.press("Space")
        page.wait_for_timeout(500)
        played = is_paused() is False
        check("Space 를 누르면 재생된다", played, f"paused={is_paused()}")
        page.keyboard.press("Space")
        page.wait_for_timeout(300)
        check("한 번 더 누르면 멈춘다", is_paused() is True, f"paused={is_paused()}")

        # 텍스트를 입력하는 중에는 Space 가 재생으로 새면 안 된다.
        # 커서를 글 끝에 못 박아 두어야 눌린 공백이 어디 들어갔는지 정확히 판정할 수 있다.
        page.evaluate(
            "(el => { el.focus(); el.setSelectionRange(el.value.length, el.value.length); })"
            "(document.querySelector('.seg-item[data-id=\"s1\"] .seg-text'))"
        )
        page.keyboard.press("Space")
        page.wait_for_timeout(250)
        check("자막을 편집하는 중에는 Space 가 재생시키지 않는다",
              is_paused() is True, f"paused={is_paused()}")
        typed = page.evaluate(
            "document.querySelector('.seg-item[data-id=\"s1\"] .seg-text').value"
        )
        check("편집 중 Space 는 글자(공백)로 입력된다", typed == "첫째 자막 문장입니다 ",
              f"내용: {typed!r}")
        # 원래대로 되돌린다
        page.evaluate(
            "(el => { el.value = '첫째 자막 문장입니다'; el.blur(); })"
            "(document.querySelector('.seg-item[data-id=\"s1\"] .seg-text'))"
        )
        page.wait_for_timeout(200)

        # ══ ← / → — 시간 이동 ═══════════════════════════════
        print("\n=== ← / → — 시간 이동 (Shift 를 함께 누르면 0.1초) ===")
        blur()
        page.evaluate("document.querySelector('#player').currentTime = 5.0")
        page.wait_for_timeout(200)

        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(200)
        t = current_time()
        check("→ 는 1초 뒤로 간다", abs(t - 6.0) < 0.05, f"5.0 → {t:.3f}")

        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(200)
        t = current_time()
        check("← 는 1초 앞으로 간다", abs(t - 5.0) < 0.05, f"6.0 → {t:.3f}")

        page.keyboard.press("Shift+ArrowRight")
        page.wait_for_timeout(200)
        t = current_time()
        check("Shift+→ 는 0.1초만 움직인다", abs(t - 5.1) < 0.02, f"5.0 → {t:.3f}")

        page.keyboard.press("Shift+ArrowLeft")
        page.wait_for_timeout(200)
        t = current_time()
        check("Shift+← 는 0.1초만 움직인다", abs(t - 5.0) < 0.02, f"5.1 → {t:.3f}")

        # ══ ↑ / ↓ — 자막 선택 이동 ═════════════════════════
        print("\n=== ↑ / ↓ — 이전 / 다음 자막 선택 ===")
        page.locator('.seg-item[data-id="s1"]').click()
        page.wait_for_timeout(250)
        blur()
        check("첫째 자막이 선택되었다", active_id() == "s1", f"선택: {active_id()!r}")

        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(250)
        check("↓ 로 다음 자막이 선택된다", active_id() == "s2", f"선택: {active_id()!r}")

        page.keyboard.press("ArrowUp")
        page.wait_for_timeout(250)
        check("↑ 로 이전 자막이 선택된다", active_id() == "s1", f"선택: {active_id()!r}")

        # ══ Enter — 편집 시작 ══════════════════════════════
        print("\n=== Enter — 선택한 자막 편집 시작 ===")
        page.keyboard.press("Enter")
        page.wait_for_timeout(250)
        focused = page.evaluate(
            "document.activeElement === "
            "document.querySelector('.seg-item[data-id=\"s1\"] .seg-text')"
        )
        check("Enter 를 누르면 그 자막의 입력칸으로 들어간다", focused is True)
        caret = page.evaluate("document.activeElement.selectionStart")
        length = page.evaluate("document.activeElement.value.length")
        check("커서가 글 끝에 놓인다 (바로 이어서 쓸 수 있다)", caret == length,
              f"커서 {caret} / 글자수 {length}")

        # ══ Ctrl+Enter — 커서 자리에서 나누기 ═══════════════
        print("\n=== Ctrl+Enter — 커서 자리에서 자막 나누기 ===")
        before = seg_count()
        page.evaluate(
            "(el => { el.focus(); el.setSelectionRange(3, 3); })"
            "(document.querySelector('.seg-item[data-id=\"s1\"] .seg-text'))"
        )
        page.keyboard.press("Control+Enter")
        page.wait_for_timeout(500)
        after_split = seg_count()
        check("Ctrl+Enter 로 자막이 하나 늘어난다", after_split == before + 1,
              f"{before}개 → {after_split}개")

        # ══ Ctrl+Z / Ctrl+Y — 되돌리기 / 다시 실행 ══════════
        print("\n=== Ctrl+Z / Ctrl+Y — 되돌리기 / 다시 실행 ===")
        blur()
        page.keyboard.press("Control+z")
        page.wait_for_timeout(500)
        after_undo = seg_count()
        check("Ctrl+Z 로 나누기가 취소된다", after_undo == before,
              f"{after_split}개 → {after_undo}개")

        page.keyboard.press("Control+y")
        page.wait_for_timeout(500)
        after_redo = seg_count()
        check("Ctrl+Y 로 다시 실행된다", after_redo == after_split,
              f"{after_undo}개 → {after_redo}개")

        # 다음 검사를 위해 원래대로
        page.keyboard.press("Control+z")
        page.wait_for_timeout(400)

        # ══ Ctrl+F — 검색창으로 ════════════════════════════
        print("\n=== Ctrl+F — 자막 검색창으로 ===")
        blur()
        page.keyboard.press("Control+f")
        page.wait_for_timeout(250)
        on_search = page.evaluate(
            "document.activeElement === document.querySelector('#seg-search')"
        )
        check("Ctrl+F 를 누르면 검색창에 커서가 간다", on_search is True)
        blur()

        # ══ Ctrl+S — 즉시 저장 ═════════════════════════════
        print("\n=== Ctrl+S — 자동 저장을 기다리지 않고 즉시 저장 ===")
        saved_before = api(f"/api/projects/{pid}")["updated_at"]
        time.sleep(1.1)  # 저장 시각(초 단위)이 반드시 달라지도록
        page.evaluate("project.name = '단축키로저장됨'")
        page.keyboard.press("Control+s")
        page.wait_for_timeout(1200)
        fresh = api(f"/api/projects/{pid}")
        check("Ctrl+S 로 저장 시각이 갱신된다", fresh["updated_at"] != saved_before,
              f"{saved_before} → {fresh['updated_at']}")
        check("Ctrl+S 로 바꾼 내용이 실제로 저장된다", fresh["name"] == "단축키로저장됨",
              f"이름: {fresh['name']!r}")

        # ══ 화면 오류 ═══════════════════════════════════════
        print("\n=== 누르는 동안 화면에서 오류가 났는가 ===")
        check("자바스크립트 오류가 없다", not errors, "; ".join(errors[:3]))

        browser.close()
finally:
    try:
        api(f"/api/projects/{pid}", "DELETE")
    except Exception:
        pass
    print("\n" + "=" * 70)
    print(f"  통과 {len(passed)}개 · 실패 {len(failed)}개")
    if failed:
        print("\n  실패한 항목:")
        for name in failed:
            print(f"    - {name}")
    print("=" * 70 + "\n")

sys.exit(1 if failed else 0)
