"""브라우저에서 실제로 눌러 보는 점검 (F-A · F-B · F-C ⓐ · F-D).

이 프로젝트에서 발견된 결함 대부분은 "코드는 그렇게 되어 있는데 화면에서는 안 되던 것"이었다.
그래서 이 점검은 코드를 읽지 않고 **진짜 브라우저를 띄워 단추를 누르고 결과를 읽는다.**

준비 (개발용 도구이며 배포되는 프로그램에는 들어가지 않는다):
    python -m pip install playwright
    python -m playwright install chromium

사용법:
    1) 개발 서버를 띄운다   python -m app          (설치본이 8765를 쓰면 --port 8766)
    2) python tests/ui_test.py
       (다른 포트면  set MOVIEFIT_TEST_URL=http://127.0.0.1:8766)
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
    """처음 열면 뜨는 사용법 안내 창을 닫는다 (열려 있으면 다른 단추를 누를 수 없다)."""
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
    sys.exit(1)

# 점검용 프로젝트를 하나 만든다 (자막 두 개, 영상 있음)
project = api("/api/projects", "POST",
              {"name": "화면점검", "video_path": str(SAMPLE), "mode": "video"})
pid = project["id"]
project["segments"] = [
    {"id": "s1", "start": 0.2, "end": 2.0, "text": "첫 번째 자막"},
    {"id": "s2", "start": 2.2, "end": 4.0, "text": "두 번째 자막"},
]
api(f"/api/projects/{pid}", "PUT", project)
print(f"점검용 프로젝트: {pid}\n")

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
        # 영상 크기를 읽어야 화면비 틀이 그려진다
        page.wait_for_function("document.querySelector('#player').videoWidth > 0", timeout=20000)
        page.wait_for_timeout(400)

        src_w = page.evaluate("document.querySelector('#player').videoWidth")
        src_h = page.evaluate("document.querySelector('#player').videoHeight")
        print(f"화면에서 읽은 영상 크기: {src_w}×{src_h}\n")

        # ══ F-D : 저장됨 단추 ═══════════════════════════════════
        print("=== F-D: '저장됨'을 실제로 눌러 본다 ===")
        save_btn = page.locator("#save-state")
        check("'저장됨'이 눌리는 요소다 (button 태그)",
              save_btn.evaluate("el => el.tagName") == "BUTTON")
        check("마우스를 올리면 손가락 모양이 된다",
              save_btn.evaluate("el => getComputedStyle(el).cursor") == "pointer")

        before = api(f"/api/projects/{pid}")["updated_at"]
        page.wait_for_timeout(1100)  # 저장 시각(초 단위)이 반드시 달라지도록
        # 무언가를 고쳐 놓고 눌러야 '눌러서 저장됐다'는 것이 증명된다
        page.evaluate("project.name = '눌러서저장됨'")
        save_btn.click()
        page.wait_for_timeout(900)

        after = api(f"/api/projects/{pid}")
        check("누르자 실제로 저장되었다 (디스크의 저장 시각이 바뀜)",
              after["updated_at"] != before, f"{before} → {after['updated_at']}")
        check("눌렀을 때의 내용이 그대로 저장되었다",
              after["name"] == "눌러서저장됨", f"이름 = {after['name']}")
        check("눌린 것이 눈에 보인다 (단추가 잠깐 밝아진다)",
              save_btn.evaluate("el => el.className").find("is-just-saved") >= 0
              or page.locator("#toast").is_visible(),
              "밝아짐 표시 또는 알림")
        check("마지막 저장 시각을 알려 준다",
              "마지막 저장" in (save_btn.get_attribute("title") or ""),
              (save_btn.get_attribute("title") or "").replace("\n", " / "))

        # ══ F-B : 위치 화살표 ═══════════════════════════════════
        print("\n=== F-B: 자막 위치 화살표를 실제로 눌러 본다 ===")
        page.evaluate("setOutput({aspect:'source'}, {snap:false})")
        page.evaluate("""
            project.style.position = {mode:'custom', preset:'bottom', x:50, y:80};
            syncStyleInputs(); applyOverlayStyle();
        """)
        page.wait_for_timeout(150)

        def pos():
            return (float(page.input_value("#style-pos-x")), float(page.input_value("#style-pos-y")))

        x0, y0 = pos()
        page.locator('[data-nudge="up"]').click()
        x1, y1 = pos()
        check("↑ 를 누르면 자막이 위로 1% 올라간다",
              abs((y0 - y1) - 1.0) < 0.001 and abs(x1 - x0) < 0.001, f"{y0} → {y1}")

        page.locator('[data-nudge="down"]').click()
        x2, y2 = pos()
        check("↓ 를 누르면 다시 1% 내려온다", abs(y2 - y0) < 0.001, f"{y1} → {y2}")

        page.locator('[data-nudge="right"]').click()
        x3, y3 = pos()
        check("→ 를 누르면 오른쪽으로 1% 간다",
              abs((x3 - x0) - 1.0) < 0.001 and abs(y3 - y0) < 0.001, f"{x0} → {x3}")

        page.locator('[data-nudge="left"]').click(modifiers=["Shift"])
        x4, y4 = pos()
        check("Shift와 함께 ← 를 누르면 5% 크게 간다",
              abs((x3 - x4) - 5.0) < 0.001, f"{x3} → {x4}")

        # 화면의 자막 오버레이가 실제로 따라 움직이는지 (숫자만 바뀌고 화면이 그대로면 안 된다)
        top_before = page.locator("#overlay").evaluate("el => el.style.top")
        page.locator('[data-nudge="up"]').click(modifiers=["Shift"])
        top_after = page.locator("#overlay").evaluate("el => el.style.top")
        check("화면의 자막도 함께 움직인다", top_before != top_after,
              f"{top_before} → {top_after}")

        # 가장자리를 넘어가지 않는지
        page.evaluate("""
            project.style.position = {mode:'custom', preset:'bottom', x:50, y:0.5};
            syncStyleInputs(); applyOverlayStyle();
        """)
        page.locator('[data-nudge="up"]').click(modifiers=["Shift"])
        _, y_edge = pos()
        check("맨 위를 넘어가지 않는다", y_edge >= 0, f"세로 {y_edge}%")

        # ══ F-A / F-C ⓐ : 화면비 ════════════════════════════════
        print("\n=== F-A · F-C ⓐ: 화면비 단추와 미리보기 틀 ===")

        def aspect_of():
            return page.evaluate("currentOutput().aspect")

        page.locator('[data-aspect="9:16"]').click()
        page.wait_for_timeout(250)
        check("[세로 9:16] 을 누르면 세로로 바뀐다", aspect_of() == "9:16", aspect_of())
        check("세로 단추에 '선택됨' 표시가 켜진다",
              "is-active" in page.locator('[data-aspect="9:16"]').get_attribute("class"))
        check("미리보기에 화면비 틀이 나타난다", page.locator("#fg-window").is_visible())

        page.locator('[data-aspect="16:9"]').click()
        page.wait_for_timeout(250)
        check("[가로 16:9] 를 눌러 가로로 되돌아온다 (한 방향이 아니다)",
              aspect_of() == "16:9", aspect_of())
        check("세로 단추의 표시는 꺼진다",
              "is-active" not in page.locator('[data-aspect="9:16"]').get_attribute("class"))

        page.locator('[data-aspect="1:1"]').click()
        page.wait_for_timeout(200)
        check("[정사각 1:1] 로도 갈 수 있다", aspect_of() == "1:1", aspect_of())

        page.locator('[data-aspect="source"]').click()
        page.wait_for_timeout(200)
        check("[원본 그대로] 로 되돌리면 틀이 사라진다",
              aspect_of() == "source" and page.locator("#frame-guide").is_hidden())

        # 틀의 위치·크기가 서버 계산과 실제로 맞는가
        page.locator('[data-aspect="9:16"]').click()
        page.wait_for_timeout(300)
        want = api(f"/api/system/framing?w={src_w}&h={src_h}&aspect=9:16&fit=crop&focus_x=50")
        box = page.locator("#video-box").bounding_box()
        win = page.locator("#fg-window").bounding_box()
        # 화면에 그려진 틀을 원본 픽셀로 환산한다
        got_w = round(win["width"] / box["width"] * src_w)
        got_x = round((win["x"] - box["x"]) / box["width"] * src_w)
        check("화면에 그려진 틀의 너비가 서버 계산과 같다",
              abs(got_w - want["width"]) <= 2, f"화면 {got_w} vs 서버 {want['width']}")
        check("화면에 그려진 틀의 위치가 서버 계산과 같다",
              abs(got_x - want["crop"]["x"]) <= 2, f"화면 {got_x} vs 서버 {want['crop']['x']}")

        # 틀 바깥이 어둡게 덮여 있는가 (무엇이 잘리는지 보여야 한다)
        shadow = page.locator("#fg-window").evaluate("el => getComputedStyle(el).boxShadow")
        check("틀 바깥이 어둡게 덮여 잘릴 부분이 보인다", "rgba(0, 0, 0" in shadow, shadow[:60])

        # ══ 미리보기 틀을 끌어서 옮기기 ═════════════════════════
        print("\n=== F-C: 미리보기 틀을 마우스로 끌어 본다 ===")
        page.evaluate("setOutput({aspect:'9:16', fit:'crop', focus_x:50}, {snap:false})")
        page.wait_for_timeout(200)
        focus_before = page.evaluate("currentOutput().focus_x")
        win = page.locator("#fg-window").bounding_box()
        cx, cy = win["x"] + win["width"] / 2, win["y"] + win["height"] / 2

        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 120, cy, steps=10)
        page.mouse.up()
        page.wait_for_timeout(250)
        focus_after = page.evaluate("currentOutput().focus_x")
        check("틀을 오른쪽으로 끌면 남길 자리가 오른쪽으로 간다",
              focus_after > focus_before + 5, f"{focus_before}% → {focus_after}%")

        moved = page.locator("#fg-window").bounding_box()
        check("끌린 만큼 틀이 실제로 옮겨졌다", moved["x"] > win["x"] + 5,
              f"{round(win['x'])} → {round(moved['x'])}")

        # 막대와 틀이 같은 값을 가리키는가
        slider_val = float(page.input_value("#aspect-focus"))
        check("옆의 [잘라낼 자리] 막대도 같은 값을 가리킨다",
              abs(slider_val - focus_after) < 1.5, f"막대 {slider_val} vs 설정 {focus_after}")

        # ══ 미리보기의 자막이 실제 내보내기와 같은 자리인가 ══════
        #
        # 자막 위치는 "출력 틀의 몇 %"로 저장된다. 잘라내기를 쓰면 미리보기 상자는 여전히
        # 원본 전체를 보여 주므로, 상자를 기준으로 그리면 자막이 엉뚱한 곳에 보인다.
        # (고치기 전 실측: 미리보기 640px vs 실제 202px — 438픽셀 어긋남)
        print("\n=== F-C: 미리보기의 자막 위치가 실제 결과와 같은가 ===")
        page.evaluate("""
            setOutput({aspect:'9:16', fit:'crop', focus_x:0}, {snap:false});
            project.style.position = {mode:'custom', preset:'bottom', x:50, y:50};
            syncStyleInputs(); applyOverlayStyle(); updateOverlay(1.0);
        """)
        page.wait_for_timeout(300)

        box = page.locator("#video-box").bounding_box()
        win = page.locator("#fg-window").bounding_box()
        ov = page.locator("#overlay").bounding_box()

        def to_src(px):
            return (px - box["x"]) / box["width"] * src_w

        win_left, win_right = to_src(win["x"]), to_src(win["x"] + win["width"])
        ov_center = to_src(ov["x"] + ov["width"] / 2)
        expect_center = win_left + (win_right - win_left) * 0.5
        check("가로 50%로 둔 자막이 미리보기에서도 '자른 틀의 한가운데'에 보인다",
              abs(ov_center - expect_center) < 8,
              f"자막 중심 {ov_center:.0f}px / 틀 한가운데 {expect_center:.0f}px "
              f"(자르는 틀 {win_left:.0f}~{win_right:.0f}px)")
        check("자막이 자르는 틀 안에 들어 있다",
              win_left - 2 <= ov_center <= win_right + 2,
              f"{ov_center:.0f}px 이 {win_left:.0f}~{win_right:.0f} 안인가")

        # 끄는 동작도 같은 기준을 쓰는가 (한쪽만 고치면 끌 때마다 자막이 튄다)
        before_x = page.evaluate("resolvedPosition(project.style)[0]")
        page.mouse.move(ov["x"] + ov["width"] / 2, ov["y"] + ov["height"] / 2)
        page.mouse.down()
        page.mouse.move(win["x"] + win["width"] * 0.25, ov["y"] + ov["height"] / 2, steps=8)
        page.mouse.up()
        page.wait_for_timeout(300)
        after_x = page.evaluate("resolvedPosition(project.style)[0]")
        ov2 = page.locator("#overlay").bounding_box()
        check("자막을 끌면 '자른 틀 기준'의 값으로 바뀐다 (25% 근처)",
              abs(after_x - 25) < 8, f"{before_x}% → {after_x}%")
        check("끈 뒤에도 자막이 화면에서 튀지 않는다 (그린 자리와 저장된 값이 일치)",
              abs(to_src(ov2["x"] + ov2["width"] / 2)
                  - (win_left + (win_right - win_left) * after_x / 100)) < 8,
              f"그린 자리 {to_src(ov2['x'] + ov2['width'] / 2):.0f}px")

        # ══ 자막이 잘릴 상황을 알려 주는가 ══════════════════════
        print("\n=== F-C: 자막이 잘릴 때 알려 주는가 ===")
        page.evaluate("""
            setOutput({aspect:'9:16', fit:'crop', focus_x:50}, {snap:false});
            project.segments[0].text = '아주 길어서 좁은 세로 화면에는 도저히 들어가지 않는 자막';
            project.style.max_chars = 40;
            project.style.position = {mode:'custom', preset:'bottom', x:88, y:50};
            syncStyleInputs(); applyOverlayStyle(); updateOverlay(1.0);
        """)
        page.wait_for_timeout(350)
        warn = page.locator("#subtitle-fit-warn")
        check("자막이 틀 밖으로 나가면 경고가 뜬다 (조용히 잘리지 않는다)",
              warn.is_visible(), (warn.text_content() or "")[:80])

        page.evaluate("""
            project.style.position = {mode:'custom', preset:'bottom', x:50, y:50};
            project.style.max_chars = 12;
            project.segments[0].text = '짧은 자막';
            syncStyleInputs(); applyOverlayStyle(); updateOverlay(1.0);
        """)
        page.wait_for_timeout(350)
        check("자막을 안쪽으로 들이면 경고가 사라진다", warn.is_hidden())

        # ══ 여백 채우기 ════════════════════════════════════════
        print("\n=== F-C: 여백 채우기 ===")
        page.locator('[data-aspect="9:16"]').click()   # '원본 그대로'면 아래 단추들이 감춰진다
        page.wait_for_timeout(250)
        page.locator('[data-fit="pad"]').click()
        page.wait_for_timeout(400)
        check("[여백 채우기] 로 바꿀 수 있다", page.evaluate("currentOutput().fit") == "pad")
        ratio = page.locator("#video-box").evaluate(
            "el => { const r = el.getBoundingClientRect(); return r.width / r.height; }")
        check("미리보기 상자가 9:16 모양(세로로 김)이 된다",
              abs(ratio - 9 / 16) < 0.02, f"가로세로비 {ratio:.4f} (9/16 = 0.5625)")
        check("흐린 배경이 켜진다", page.locator("#player-bg").is_visible())

        page.locator("#aspect-pad-blur").uncheck()
        page.wait_for_timeout(300)
        check("흐린 배경을 끄면 검은 배경이 된다",
              page.locator("#player-bg").is_hidden()
              and "is-pad-black" in page.locator("#video-box").get_attribute("class"))

        # ══ 저장되는가 ════════════════════════════════════════
        print("\n=== 설정이 실제로 저장되는가 ===")
        page.locator('[data-aspect="9:16"]').click()
        page.locator('[data-fit="crop"]').click()
        page.wait_for_timeout(200)
        page.locator("#save-state").click()
        page.wait_for_timeout(900)
        saved = api(f"/api/projects/{pid}")
        check("화면비 설정이 디스크에 저장되었다",
              (saved.get("output") or {}).get("aspect") == "9:16",
              json.dumps(saved.get("output"), ensure_ascii=False))

        # 새로고침해도 남아 있는가
        page.reload(wait_until="networkidle")
        dismiss_coach(page)
        page.wait_for_function("document.querySelector('#player').videoWidth > 0", timeout=20000)
        page.wait_for_timeout(400)
        check("새로고침해도 화면비 설정이 남아 있다",
              page.evaluate("currentOutput().aspect") == "9:16")
        check("새로고침 후에도 세로 단추에 표시가 켜져 있다",
              "is-active" in page.locator('[data-aspect="9:16"]').get_attribute("class"))

        # ══ 자바스크립트 오류가 없었는가 ════════════════════════
        print("\n=== 브라우저 오류 ===")
        real_errors = [e for e in errors if "no sw" not in e and "favicon" not in e]
        check("화면을 쓰는 동안 자바스크립트 오류가 없었다",
              not real_errors, "; ".join(real_errors[:3]) if real_errors else "0건")

        browser.close()
finally:
    try:
        api(f"/api/projects/{pid}", "DELETE")
        print(f"\n점검용 프로젝트를 지웠습니다: {pid}")
    except Exception as exc:
        print(f"\n점검용 프로젝트를 지우지 못했습니다: {exc}")

print("\n" + "=" * 62)
print(f"  통과 {len(passed)}개 · 실패 {len(failed)}개")
if failed:
    print("\n  실패한 항목:")
    for name in failed:
        print(f"   - {name}")
print("=" * 62)
sys.exit(1 if failed else 0)
