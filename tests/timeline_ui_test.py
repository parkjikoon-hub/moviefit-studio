"""타임라인을 **실제 마우스로 끌고 눌러서** 확인한다 (지인 의견 대응, 2026-11-04).

사용법:
    1) 개발 서버를 띄운다   python -m app --port 8766
    2) set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
    3) python tests/timeline_ui_test.py

왜 따로 있나 — 받은 의견이 "마우스로 끌어서 늘이고 줄이는 기능이 있으면 좋겠다"였다.
끌기 기능은 이미 있었는데 아무도 몰랐고, 끌고 나면 옆 자막과 겹치거나 Ctrl+Z 가
거짓말을 했다 (docs/REVIEW_timeline_usability.md). 이 점검은 그 하나하나를 막는다.

이 점검이 확인하는 것:
  1. 되돌리기가 화면 효과·화면비까지 실제로 되돌리는가
  2. 손잡이가 잡을 만큼 넓은가
  3. 끄는 동안 시각 말풍선이 뜨고, 놓으면 사라지는가
  4. 옆 자막에 가까이 가면 착 붙는가, Alt 를 누르면 안 붙는가
  5. 옆 자막을 넘어가지 못하게 막는가
  6. 눈금·재생선·빈 곳을 눌러 재생 위치를 옮길 수 있는가
  7. Ctrl + 휠로 확대·축소가 되고, 마우스 아래 시각이 제자리에 남는가
  8. 타임라인을 키우면 막대도 커지는가
  9. 처음 안내창과 단축키 표가 끌기를 알려 주는가
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

# 자막 셋. 둘째 자막의 시작을 0.1초 눈금에서 벗어난 4.05초로 둔다 —
# 그래야 "붙었다"와 "0.1초 반올림으로 우연히 같아졌다"가 구별된다.
SEGS = [
    {"id": "s1", "start": 1.0, "end": 3.0, "text": "첫째 자막"},
    {"id": "s2", "start": 4.05, "end": 6.0, "text": "둘째 자막"},
    {"id": "s3", "start": 7.0, "end": 9.0, "text": "셋째 자막"},
]


def reset_segments(page) -> None:
    page.evaluate(f"project.segments = {json.dumps(SEGS, ensure_ascii=False)}; renderAll();")
    page.wait_for_timeout(150)


def seg(page, sid: str) -> dict:
    return page.evaluate(f"JSON.parse(JSON.stringify(project.segments.find(s => s.id === '{sid}')))")


def box_of(page, selector: str) -> dict | None:
    loc = page.locator(selector)
    return loc.first.bounding_box() if loc.count() else None


def x_of_time(page, t: float) -> float:
    """타임라인 위에서 t 초가 있는 화면 가로 위치(px)."""
    return page.evaluate(f"document.querySelector('#tl-inner').getBoundingClientRect().left + {t} * pxPerSec")


def close_coach(page) -> None:
    """처음 안내창이 떠 있으면 닫는다 (눈금 줄을 덮는다)."""
    if page.locator("#coach").is_visible():
        page.locator("#coach-close").click()
        page.wait_for_timeout(150)


def drag(page, x0: float, y: float, x1: float, alt: bool = False, release: bool = True) -> None:
    page.mouse.move(x0, y)
    page.mouse.down()
    if alt:
        page.keyboard.down("Alt")
    page.mouse.move(x1, y, steps=12)
    if release:
        page.mouse.up()
        if alt:
            page.keyboard.up("Alt")
        page.wait_for_timeout(250)


# ── 0. 고친 화면이 사용자에게 실제로 닿는가 ─────────────────
# 표시가 없으면 브라우저가 옛 app.js 를 며칠씩 그대로 쓴다. 그러면 아래를 다 고쳐도
# 새 판을 설치한 사람 눈에는 아무것도 안 바뀐다 (2026-11-04 실제로 겪었다).
print("=== 0. 화면 파일에 '매번 확인하라(no-cache)' 표시가 붙는가 ===")
for _path in ["/", "/index.html", "/app.js", "/style.css", "/sw.js"]:
    with urllib.request.urlopen(BASE + _path, timeout=10) as _res:
        _cc = _res.headers.get("Cache-Control") or ""
    check(f"{_path} 에 no-cache 표시가 있다", "no-cache" in _cc, _cc or "표시 없음")
print()

project = api("/api/projects", "POST",
              {"name": "타임라인점검", "video_path": str(SAMPLE), "mode": "video"})
pid = project["id"]
project["segments"] = SEGS
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

        # ── 9. 안내 (새 브라우저라 안내창이 떠 있어야 한다) ─────────
        print("=== 9. 처음 안내창과 단축키 표 ===")
        coach_visible = page.locator("#coach").is_visible()
        coach_text = page.locator("#coach").inner_text() if coach_visible else ""
        check("처음 안내창이 뜬다", coach_visible)
        check("안내창이 막대를 끌어 시간을 바꾸는 법을 알려 준다",
              "끌어" in coach_text and "양 끝" in coach_text, coach_text[:120].replace("\n", " "))
        if coach_visible:
            page.locator("#coach-close").click()
            page.wait_for_timeout(150)
        table = page.locator("#shortcuts").inner_text()
        check("단축키 표에 Ctrl + 휠 확대가 있다", "휠" in table)
        check("단축키 표에 Alt 끌기(붙지 않게)가 있다", "Alt" in table)

        page.wait_for_function("document.querySelector('#player').videoWidth > 0", timeout=20000)
        page.evaluate("zoomFit()")
        page.wait_for_timeout(200)
        reset_segments(page)

        # 효과 막대 하나를 1초 자리에 놓는다 (단추로 — 사용자가 하는 그대로)
        page.wait_for_function("document.querySelectorAll('#fx-kinds button').length > 0", timeout=10000)
        page.evaluate("document.querySelector('#player').currentTime = 1.0")
        page.wait_for_timeout(300)
        page.locator("#fx-kinds button").first.click()
        page.wait_for_timeout(300)

        # ── 1. 되돌리기 ──────────────────────────────────────
        print("\n=== 1. 되돌리기가 효과와 화면비까지 되돌리는가 ===")
        fx_before = page.evaluate("project.effects[0].start")
        fb = box_of(page, ".tl-fx")
        cy = fb["y"] + fb["height"] / 2
        cx = fb["x"] + fb["width"] / 2
        drag(page, cx, cy, cx + page.evaluate("pxPerSec") * 1.0)
        fx_after = page.evaluate("project.effects[0].start")
        check("효과 막대를 끌면 시작 시각이 바뀐다", fx_after > fx_before + 0.5, f"{fx_before} → {fx_after}")
        page.keyboard.press("Control+z")
        page.wait_for_timeout(250)
        fx_undo = page.evaluate("project.effects[0].start")
        check("Ctrl+Z 를 누르면 효과 막대가 원래 시각으로 돌아온다",
              abs(fx_undo - fx_before) < 0.01, f"끈 뒤 {fx_after} → 되돌린 뒤 {fx_undo} (원래 {fx_before})")
        check("되돌린 효과 막대가 화면에서도 제자리에 그려진다",
              abs(box_of(page, ".tl-fx")["x"] - fb["x"]) < 2)
        page.keyboard.press("Control+y")
        page.wait_for_timeout(250)
        check("Ctrl+Y 를 누르면 다시 옮겨진다",
              abs(page.evaluate("project.effects[0].start") - fx_after) < 0.01)

        aspect0 = page.evaluate("currentOutput().aspect")
        page.evaluate("setOutput({aspect: '9:16'})")
        page.wait_for_timeout(200)
        check("화면비를 바꾸면 값이 바뀐다", page.evaluate("currentOutput().aspect") == "9:16")
        page.keyboard.press("Control+z")
        page.wait_for_timeout(250)
        check("Ctrl+Z 를 누르면 화면비가 원래대로 돌아온다",
              page.evaluate("currentOutput().aspect") == aspect0,
              f"원래 {aspect0} / 되돌린 뒤 {page.evaluate('currentOutput().aspect')}")
        reset_segments(page)

        # ── 2. 손잡이 ────────────────────────────────────────
        print("\n=== 2. 손잡이가 잡을 만큼 넓은가 ===")
        gw = page.evaluate("document.querySelector('.tl-clip .grip-r').getBoundingClientRect().width")
        fw = page.evaluate("document.querySelector('.tl-fx .grip-r').getBoundingClientRect().width")
        check("자막 막대 손잡이가 12px 이상이다", gw >= 12, f"{gw:.1f}px")
        check("효과 막대 손잡이가 12px 이상이다", fw >= 12, f"{fw:.1f}px")

        # ── 3. 말풍선 ────────────────────────────────────────
        print("\n=== 3. 끄는 동안 시각 말풍선 ===")
        gr = box_of(page, '.tl-clip[data-id="s1"] .grip-r')
        gy = gr["y"] + gr["height"] / 2
        gx = gr["x"] + gr["width"] / 2
        drag(page, gx, gy, gx - 30, release=False)
        tip_on = page.evaluate("(() => { const t = document.querySelector('#tl-drag-tip');"
                               " return t && !t.hidden && getComputedStyle(t).display !== 'none'"
                               " ? t.textContent : null; })()")
        check("끄는 동안 말풍선이 뜬다", bool(tip_on), str(tip_on))
        check("말풍선에 시작 → 끝 시각이 적혀 있다", bool(tip_on) and "→" in tip_on, str(tip_on))
        page.mouse.up()
        page.wait_for_timeout(200)
        tip_off = page.evaluate("(() => { const t = document.querySelector('#tl-drag-tip');"
                                " return !t || t.hidden || getComputedStyle(t).display === 'none'; })()")
        check("손을 놓으면 말풍선이 사라진다", tip_off)
        reset_segments(page)

        # ── 4. 붙기 ──────────────────────────────────────────
        print("\n=== 4. 옆 자막에 착 붙는가 ===")
        gr = box_of(page, '.tl-clip[data-id="s1"] .grip-r')
        gx = gr["x"] + gr["width"] / 2
        gy = gr["y"] + gr["height"] / 2
        # 손잡이 가운데와 막대 끝의 거리를 그대로 지켜서, 막대 끝이 4.05초에서 4px 앞에 오도록 끈다
        edge_offset = gr["x"] + gr["width"] - gx
        target = x_of_time(page, 4.05) - 4 - edge_offset
        drag(page, gx, gy, target)
        s1 = seg(page, "s1")
        check("끝이 옆 자막 시작(4.05초) 가까이 오면 정확히 거기에 붙는다",
              abs(s1["end"] - 4.05) < 0.001, f"끝 {s1['end']}초")
        reset_segments(page)

        gr = box_of(page, '.tl-clip[data-id="s1"] .grip-r')
        gx = gr["x"] + gr["width"] / 2
        drag(page, gx, gy, target, alt=True)
        s1 = seg(page, "s1")
        check("Alt 를 누른 채 끌면 붙지 않는다", abs(s1["end"] - 4.05) > 0.001, f"끝 {s1['end']}초")
        reset_segments(page)

        # ── 5. 겹침 막기 ─────────────────────────────────────
        print("\n=== 5. 옆 자막을 넘어가지 못하는가 ===")
        gr = box_of(page, '.tl-clip[data-id="s1"] .grip-r')
        gx = gr["x"] + gr["width"] / 2
        drag(page, gx, gy, x_of_time(page, 5.5))
        s1 = seg(page, "s1")
        check("끝을 옆 자막 안까지 끌어도 옆 자막 시작에서 멈춘다",
              abs(s1["end"] - 4.05) < 0.001, f"끝 {s1['end']}초")
        reset_segments(page)

        gl = box_of(page, '.tl-clip[data-id="s2"] .grip-l')
        gx = gl["x"] + gl["width"] / 2
        drag(page, gx, gy, x_of_time(page, 2.0))
        s2 = seg(page, "s2")
        check("시작을 앞 자막 안까지 끌어도 앞 자막 끝에서 멈춘다",
              abs(s2["start"] - 3.0) < 0.001, f"시작 {s2['start']}초")
        reset_segments(page)

        b3 = box_of(page, '.tl-clip[data-id="s3"]')
        cx = b3["x"] + b3["width"] / 2
        drag(page, cx, gy, cx - page.evaluate("pxPerSec") * 3.0)
        s3 = seg(page, "s3")
        check("막대째 옮겨도 앞 자막을 덮지 않는다", s3["start"] >= 6.0 - 0.001, f"시작 {s3['start']}초")
        check("막대째 옮겨도 길이는 그대로다", abs((s3["end"] - s3["start"]) - 2.0) < 0.001,
              f"{s3['start']}~{s3['end']}")
        reset_segments(page)

        # ── 6. 재생 위치 ─────────────────────────────────────
        print("\n=== 6. 재생 위치 옮기기 ===")
        ruler = box_of(page, "#tl-ruler")
        ry = ruler["y"] + ruler["height"] / 2
        page.mouse.click(x_of_time(page, 5.0), ry)
        page.wait_for_timeout(300)
        t = page.evaluate("document.querySelector('#player').currentTime")
        check("눈금 줄을 누르면 그 시각으로 간다", abs(t - 5.0) < 0.15, f"{t:.2f}초")

        drag(page, x_of_time(page, 2.0), ry, x_of_time(page, 7.0))
        t = page.evaluate("document.querySelector('#player').currentTime")
        check("눈금 줄을 누른 채 끌면 재생 위치가 따라온다", abs(t - 7.0) < 0.15, f"{t:.2f}초")

        head = box_of(page, ".tl-playhead-grip")
        check("재생선 머리에 잡을 곳이 있다", bool(head) and head["width"] >= 10,
              f"{head['width'] if head else None}px")
        if head:
            hx, hy = head["x"] + head["width"] / 2, head["y"] + head["height"] / 2
            drag(page, hx, hy, x_of_time(page, 3.0))
            t = page.evaluate("document.querySelector('#player').currentTime")
            check("재생선 머리를 끌면 재생 위치가 옮겨진다", abs(t - 3.0) < 0.15, f"{t:.2f}초")

        fxt = box_of(page, "#tl-fx-track")
        page.mouse.click(x_of_time(page, 8.5), fxt["y"] + fxt["height"] / 2)
        page.wait_for_timeout(300)
        t = page.evaluate("document.querySelector('#player').currentTime")
        check("효과 줄의 빈 곳을 눌러도 그 시각으로 간다", abs(t - 8.5) < 0.15, f"{t:.2f}초")

        # ── 7. 확대·축소 ─────────────────────────────────────
        print("\n=== 7. Ctrl + 휠 확대·축소 ===")
        p0 = page.evaluate("pxPerSec")
        sc = box_of(page, "#tl-scroll")
        mx, my = sc["x"] + sc["width"] * 0.5, sc["y"] + sc["height"] * 0.6
        t_under = page.evaluate(f"({mx} - document.querySelector('#tl-inner').getBoundingClientRect().left) / pxPerSec")
        page.mouse.move(mx, my)
        page.keyboard.down("Control")
        page.mouse.wheel(0, -300)
        page.keyboard.up("Control")
        page.wait_for_timeout(300)
        p1 = page.evaluate("pxPerSec")
        t_after = page.evaluate(f"({mx} - document.querySelector('#tl-inner').getBoundingClientRect().left) / pxPerSec")
        check("Ctrl + 휠을 위로 굴리면 확대된다", p1 > p0 * 1.1, f"{p0:.1f} → {p1:.1f} px/초")
        check("확대해도 마우스 아래 시각이 제자리에 남는다", abs(t_after - t_under) < 0.3,
              f"{t_under:.2f}초 → {t_after:.2f}초")
        page.keyboard.down("Control")
        page.mouse.wheel(0, 300)
        page.keyboard.up("Control")
        page.wait_for_timeout(300)
        check("Ctrl + 휠을 아래로 굴리면 축소된다", page.evaluate("pxPerSec") < p1, f"{page.evaluate('pxPerSec'):.1f}")
        page.evaluate("zoomFit()")
        page.wait_for_timeout(200)

        # ── 8. 막대 높이 ─────────────────────────────────────
        print("\n=== 8. 타임라인을 키우면 막대도 커지는가 ===")
        h0 = box_of(page, '.tl-clip[data-id="s1"]')["height"]
        sp = box_of(page, "#split-timeline")
        sx, sy = sp["x"] + sp["width"] / 2, sp["y"] + sp["height"] / 2
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(sx, sy + 60, steps=8)
        page.mouse.up()
        page.wait_for_timeout(300)
        h1 = box_of(page, '.tl-clip[data-id="s1"]')["height"]
        check("타임라인 높이를 늘리면 자막 막대도 높아진다", h1 > h0 + 20, f"{h0:.0f} → {h1:.0f}px")
        clip = box_of(page, '.tl-clip[data-id="s1"]')
        track = box_of(page, "#tl-track")
        check("자막 막대가 자막 줄 밖으로 삐져나오지 않는다",
              clip["y"] + clip["height"] <= track["y"] + track["height"] + 1,
              f"막대 아래 {clip['y'] + clip['height']:.0f} / 줄 아래 {track['y'] + track['height']:.0f}")
        page.evaluate("localStorage.clear()")

        # ── 10. 사진 프로젝트에서 되돌리면 재생 시계도 따라오는가 ──
        # 독립 검증에서 잡혔다: 사진을 빼고 Ctrl+Z 하면 사진은 돌아오는데 시계는 짧은 채라
        # 돌아온 셋째 사진을 미리보기로 볼 수 없었다.
        print("\n=== 10. 사진 프로젝트 되돌리기와 재생 시계 ===")
        photos = sorted((ROOT / "tests" / "sample" / "images").glob("*.*"))[:3]
        if len(photos) < 3:
            check("사진 샘플이 있다 (python tools/make_sample_images.py --count 30)", False)
        else:
            ph = api("/api/projects", "POST", {"name": "타임라인점검_사진", "mode": "video"})
            ph["images"] = [{"id": f"i{i}", "path": str(p), "duration": 3.0, "seg_id": None}
                            for i, p in enumerate(photos)]
            ph["canvas"] = {"width": 1920, "height": 1080}
            api(f"/api/projects/{ph['id']}", "PUT", ph)
            try:
                page.goto(f"{BASE}/?project={ph['id']}", wait_until="networkidle")
                close_coach(page)
                page.wait_for_function("document.querySelector('#player').duration > 8", timeout=20000)
                page.evaluate("snapshot(); projectImages().splice(2, 1); afterPhotosChanged();")
                page.wait_for_function("document.querySelector('#player').duration < 7", timeout=10000)
                page.keyboard.press("Control+z")
                page.wait_for_timeout(300)
                ok = True
                try:
                    page.wait_for_function("document.querySelector('#player').duration > 8.5", timeout=10000)
                except Exception:
                    ok = False
                dur = page.evaluate("document.querySelector('#player').duration")
                check("사진을 빼고 되돌리면 사진이 3장으로 돌아온다",
                      page.evaluate("projectImages().length") == 3)
                check("되돌리면 재생 시계도 9초로 돌아온다", ok, f"{dur:.2f}초")
                # 지우기 전에 저장을 끝내 둔다 — 안 그러면 다음 페이지로 넘어갈 때 지워진 프로젝트에 저장하려 한다
                page.evaluate("saveNow()")
                page.wait_for_timeout(800)
            finally:
                api(f"/api/projects/{ph['id']}", "DELETE")

        # ── 11. 영상이 없는 나레이션 작업에서 재생선에 붙는가 ──────
        print("\n=== 11. 나레이션 작업에서 재생선에 붙기 ===")
        nr = api("/api/projects", "POST", {"name": "타임라인점검_대본", "mode": "script"})
        nr["segments"] = [{"id": "n1", "start": 0.5, "end": 1.5, "text": "첫 문장"},
                          {"id": "n2", "start": 6.0, "end": 7.0, "text": "둘째 문장"}]
        api(f"/api/projects/{nr['id']}", "PUT", nr)
        try:
            page.goto(f"{BASE}/?project={nr['id']}", wait_until="networkidle")
            close_coach(page)
            page.wait_for_selector('.tl-clip[data-id="n1"]', timeout=10000)
            page.evaluate("setZoom(60)")
            page.wait_for_timeout(200)
            ruler = box_of(page, "#tl-ruler")
            page.mouse.click(x_of_time(page, 3.33), ruler["y"] + ruler["height"] / 2)
            page.wait_for_timeout(200)
            head_t = page.evaluate("playheadTime")
            gr = box_of(page, '.tl-clip[data-id="n1"] .grip-r')
            gx, gy2 = gr["x"] + gr["width"] / 2, gr["y"] + gr["height"] / 2
            off = gr["x"] + gr["width"] - gx
            drag(page, gx, gy2, x_of_time(page, head_t) - 3 - off)
            end = page.evaluate("project.segments.find(s => s.id === 'n1').end")
            check("영상이 없어도 막대 끝이 옮겨 둔 재생선에 붙는다",
                  head_t > 3.0 and abs(end - round(head_t, 3)) < 0.002,
                  f"재생선 {head_t:.3f}초 / 끝 {end}초")

            # ── 12. 고치자마자 창을 떠나도 저장되는가 (자동 저장 2초를 기다리지 않고) ──
            print("\n=== 12. 고치자마자 창을 떠나도 저장되는가 ===")
            page.goto("about:blank")
            page.wait_for_timeout(1000)
            saved = api(f"/api/projects/{nr['id']}")
            saved_end = next(s["end"] for s in saved["segments"] if s["id"] == "n1")
            check("끈 직후 창을 떠나도 바뀐 끝 시각이 서버에 저장되어 있다",
                  abs(saved_end - end) < 0.002, f"화면 {end}초 / 서버 {saved_end}초")
        finally:
            api(f"/api/projects/{nr['id']}", "DELETE")

        # ── 자바스크립트 오류 ────────────────────────────────
        print("\n=== 자바스크립트 오류 ===")
        real = [e for e in errors if "no sw" not in e and "favicon" not in e]
        check("자바스크립트 오류가 하나도 없다", not real, "없음" if not real else " / ".join(real[:3]))

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
