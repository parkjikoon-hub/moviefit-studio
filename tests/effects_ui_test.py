"""화면 효과 패널을 **실제로 클릭해서** 확인한다.

사용법:
    1) 개발 서버를 띄운다   python -m app --port 8766
    2) set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
    3) python tests/effects_ui_test.py

왜 따로 있나 — `memory/verify-ui-by-actually-clicking.md`:
서버 점검이 다 통과해도 화면에서 단추가 안 눌리거나, 눌러도 아무 일이 안 일어나거나,
막대가 안 보이는 일이 있다. 그건 사람이(또는 브라우저를 몰아서) 눌러 봐야만 드러난다.

이 점검이 확인하는 것:
  · 효과 단추가 서버 목록으로 채워지는가
  · 누르면 **지금 재생 위치**에 막대가 실제로 생기는가 (화면에 보이는가)
  · 막대를 마우스로 끌면 시각이 실제로 바뀌는가
  · 세기 단추가 저장값을 실제로 바꾸는가
  · 지우기가 실제로 지우는가
  · 저장했다가 다시 열면 그대로 남아 있는가
  · 자바스크립트 오류가 하나도 없는가
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
SAMPLE = ROOT / "tests" / "sample" / "sample_10s.mp4"

passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    print(f"[{'  OK  ' if ok else ' FAIL '}] {name}" + (f"   — {detail}" if detail else ""))
    return ok


def api(path: str, method: str = "GET", body: dict | None = None, timeout: int = 60):
    url = BASE + urllib.parse.quote(path, safe="/?&=.:%-")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8") or "{}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright 가 설치되어 있지 않습니다.")
    print("  python -m pip install playwright")
    print("  python -m playwright install chromium")
    sys.exit(2)

if not SAMPLE.is_file():
    print(f"샘플 영상이 없습니다: {SAMPLE}  (python tools/make_sample.py)")
    sys.exit(1)

project = api("/api/projects", "POST",
              {"name": "효과화면점검", "video_path": str(SAMPLE), "mode": "video"})
pid = project["id"]
project["segments"] = [{"id": "s1", "start": 0.2, "end": 2.0, "text": "자막 하나"}]
api(f"/api/projects/{pid}", "PUT", project)
print(f"점검용 프로젝트: {pid}\n")


def dismiss_coach(page) -> None:
    """처음 켤 때 나오는 안내를 닫는다 (있으면)."""
    for sel in ["#coach-close", ".coach-close", "#btn-coach-close"]:
        box = page.locator(sel)
        if box.count() and box.first.is_visible():
            box.first.click()
            page.wait_for_timeout(150)
            return


try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                if m.type == "error" else None)

        page.goto(f"{BASE}/?project={pid}", wait_until="networkidle")
        dismiss_coach(page)
        page.wait_for_function("document.querySelector('#player').videoWidth > 0", timeout=20000)

        # ── 효과 단추가 서버 목록으로 채워졌는가 ──────────────
        print("=== 1. 효과 단추 ===")
        page.wait_for_function("document.querySelectorAll('#fx-kinds button').length > 0", timeout=10000)
        labels = page.eval_on_selector_all("#fx-kinds button", "els => els.map(e => e.textContent.trim())")
        check("효과 단추가 서버 목록으로 채워진다", len(labels) > 0, f"단추: {labels}")
        check("단추에 한국어 이름이 보인다", any("줌" in t for t in labels), f"단추: {labels}")

        # ── 누르면 막대가 실제로 생기는가 ────────────────────
        print("\n=== 2. 누르면 막대가 생기는가 ===")
        check("처음에는 막대가 하나도 없다",
              page.eval_on_selector_all(".tl-fx", "els => els.length") == 0)

        page.evaluate("document.querySelector('#player').currentTime = 2.0")
        page.wait_for_timeout(300)
        page.locator("#fx-kinds button").first.click()
        page.wait_for_timeout(400)

        bars = page.evaluate("JSON.parse(JSON.stringify(project.effects || []))")
        check("단추를 누르면 막대가 하나 생긴다", len(bars) == 1, f"실제 {bars}")
        check("막대가 **지금 재생 위치**에서 시작한다",
              bars and abs(bars[0]["start"] - 2.0) < 0.3, f"시작 {bars[0]['start'] if bars else None}초")
        check("막대가 타임라인에 실제로 그려진다",
              page.eval_on_selector_all(".tl-fx", "els => els.length") == 1)
        check("막대가 눈에 보인다", page.locator(".tl-fx").first.is_visible())

        box = page.locator(".tl-fx").first.bounding_box()
        check("막대의 너비가 0이 아니다", box and box["width"] > 5,
              f"너비 {round(box['width']) if box else None}px")

        # 효과 띠가 타임라인 상자 **안**에 들어 있는가.
        # 밖으로 밀려나면 아래에 있는 단추 위에 놓여 마우스를 빼앗긴다. 오류는 안 난다.
        fits = page.evaluate("""() => {
          const t = document.querySelector('#tl-fx-track').getBoundingClientRect();
          const s = document.querySelector('#tl-scroll').getBoundingClientRect();
          return { 띠아래: Math.round(t.bottom), 상자아래: Math.round(s.bottom),
                   들어감: t.bottom <= s.bottom + 1 };
        }""")
        check("효과 띠가 타임라인 상자 안에 들어 있다", fits["들어감"],
              f"띠 아래끝 {fits['띠아래']}px / 상자 아래끝 {fits['상자아래']}px")

        # 막대 한가운데를 눌렀을 때 **실제로 막대가 눌리는가.**
        # 다른 것이 위에 덮여 있으면 끌기가 조용히 죽는다.
        top = page.evaluate("([x,y]) => { const el = document.elementFromPoint(x,y);"
                            " return el ? (el.className || el.tagName) : '없음'; }",
                            [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2])
        check("막대 한가운데를 누르면 막대가 눌린다 (다른 것이 덮고 있지 않다)",
              "tl-fx" in str(top) or "grip" in str(top),
              f"그 자리의 최상위 요소: {top}")

        # ── 끌면 시각이 바뀌는가 ─────────────────────────────
        print("\n=== 3. 막대를 끌면 시각이 바뀌는가 ===")
        before = page.evaluate("project.effects[0].start")
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 90, cy, steps=10)
        page.mouse.up()
        page.wait_for_timeout(400)
        after = page.evaluate("project.effects[0].start")
        check("오른쪽으로 끌면 시작 시각이 뒤로 간다", after > before + 0.2,
              f"{before}초 → {after}초")

        moved = page.locator(".tl-fx").first.bounding_box()
        check("끌린 만큼 막대도 실제로 옮겨졌다", moved and moved["x"] > box["x"] + 5,
              f"{round(box['x'])} → {round(moved['x']) if moved else None}")

        # ── 세기 단추 ────────────────────────────────────────
        print("\n=== 4. 세기 단추 ===")
        check("막대를 고르면 세기 칸이 나타난다", page.locator("#fx-selected").is_visible())
        page.locator('.fx-strength[data-strength="high"]').click()
        page.wait_for_timeout(250)
        check("세기 단추를 누르면 저장값이 바뀐다",
              page.evaluate("project.effects[0].strength") == "high",
              f"실제 {page.evaluate('project.effects[0].strength')}")
        check("고른 세기 단추에 표시가 된다",
              "is-active" in (page.get_attribute('.fx-strength[data-strength="high"]', "class") or ""))

        # ── 저장하고 다시 열어도 남아 있는가 ──────────────────
        print("\n=== 5. 저장하고 다시 열기 ===")
        page.evaluate("saveNow()")
        page.wait_for_timeout(1500)
        saved = api(f"/api/projects/{pid}")
        check("서버에 효과가 저장되었다", len(saved.get("effects") or []) == 1,
              f"실제 {saved.get('effects')}")
        check("저장된 효과의 세기가 '많이'다",
              (saved.get("effects") or [{}])[0].get("strength") == "high",
              f"실제 {(saved.get('effects') or [{}])[0].get('strength')}")

        page.goto(f"{BASE}/?project={pid}", wait_until="networkidle")
        dismiss_coach(page)
        page.wait_for_function("document.querySelectorAll('.tl-fx').length > 0", timeout=15000)
        check("다시 열어도 막대가 그대로 보인다",
              page.eval_on_selector_all(".tl-fx", "els => els.length") == 1)

        # ── 지우기 ───────────────────────────────────────────
        print("\n=== 6. 지우기 ===")
        page.locator(".tl-fx").first.click()
        page.wait_for_timeout(250)
        page.locator("#fx-delete").click()
        page.wait_for_timeout(300)
        check("지우기를 누르면 막대가 사라진다",
              page.eval_on_selector_all(".tl-fx", "els => els.length") == 0)
        check("저장값에서도 사라진다",
              page.evaluate("(project.effects || []).length") == 0)

        # ── 등록표에 붙인 효과가 화면에 저절로 나오는가 ───────
        #    효과 띠 뼈대의 값어치가 "등록표에 한 줄 더하면 끝"이라는 것이었다.
        #    그 말이 사실인지는 **화면을 눌러 봐야** 안다.
        print("\n=== 7. 등록표에 붙인 효과가 화면에 나오는가 ===")
        server_kinds = {k["kind"]: k["label"]
                        for k in api("/api/system/effect-kinds").get("kinds", [])}
        shown = page.eval_on_selector_all(
            "#fx-kinds button", "els => els.map(e => e.textContent.trim())")
        check("서버에 등록된 효과가 하나도 빠짐없이 단추로 나온다",
              all(any(label in text for text in shown) for label in server_kinds.values()),
              f"서버 {sorted(server_kinds.values())} / 화면 {shown}")

        for kind, label in (("rain", "비"), ("snow", "눈")):
            page.evaluate("document.querySelector('#player').currentTime = 1.0")
            page.wait_for_timeout(200)
            page.locator(f'#fx-kinds button:has-text("{label}")').first.click()
            page.wait_for_timeout(400)

            made = page.evaluate("JSON.parse(JSON.stringify(project.effects || []))")
            check(f"[{label}] 단추를 누르면 그 종류의 막대가 생긴다",
                  len(made) == 1 and made[0]["kind"] == kind, f"실제 {made}")

            drawn = page.locator(".tl-fx").first
            check(f"[{label}] 막대가 타임라인에 그려지고 이름이 적힌다",
                  drawn.is_visible() and label in (drawn.text_content() or ""),
                  f"막대에 적힌 글자: {(drawn.text_content() or '').strip()!r}")

            spot_box = drawn.bounding_box()
            over = page.evaluate(
                "([x,y]) => { const el = document.elementFromPoint(x,y);"
                " return el ? (el.className || el.tagName) : '없음'; }",
                [spot_box["x"] + spot_box["width"] / 2,
                 spot_box["y"] + spot_box["height"] / 2])
            check(f"[{label}] 막대 한가운데를 누르면 막대가 눌린다 (덮인 것이 없다)",
                  "tl-fx" in str(over) or "grip" in str(over), f"그 자리의 요소: {over}")

            drawn.click()
            page.wait_for_timeout(200)
            page.locator('.fx-strength[data-strength="low"]').click()
            page.wait_for_timeout(200)
            check(f"[{label}] 세기를 바꾸면 저장값이 바뀐다",
                  page.evaluate("project.effects[0].strength") == "low",
                  f"실제 {page.evaluate('project.effects[0].strength')}")

            page.locator("#fx-delete").click()
            page.wait_for_timeout(250)
            check(f"[{label}] 지우면 사라진다",
                  page.eval_on_selector_all(".tl-fx", "els => els.length") == 0)

        # ── 자바스크립트 오류 ────────────────────────────────
        print("\n=== 8. 자바스크립트 오류 ===")
        real = [e for e in errors if "no sw" not in e and "favicon" not in e]
        check("자바스크립트 오류가 하나도 없다", not real,
              "없음" if not real else " / ".join(real[:3]))

        browser.close()
finally:
    try:
        api(f"/api/projects/{pid}", "DELETE")
        print(f"\n점검용 프로젝트를 지웠습니다: {pid}")
    except Exception:
        pass


print("\n" + "=" * 62)
print(f"  통과 {len(passed)}개 · 실패 {len(failed)}개")
if failed:
    print("\n  실패한 항목:")
    for name in failed:
        print(f"   - {name}")
print("=" * 62)
sys.exit(1 if failed else 0)
