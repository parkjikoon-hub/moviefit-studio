"""사진·음원 프로젝트를 **브라우저에서 실제로 눌러 보는** 점검 (Phase 6 단계 3·5).

왜 따로 있나: 사진 영상에서 가장 비싼 결함은 "미리보기와 결과물이 다른 것"이다
(memory/preview-must-use-the-output-frame.md — 자막이 438픽셀 어긋난 적이 있다).
그 결함은 코드를 읽어서는 보이지 않는다. 화면을 띄워 재생을 누르고, 자막을 끌어
보고, 화면비를 바꿔 봐야 드러난다.

준비:
    python -m pip install playwright
    python -m playwright install chromium
    python tools/make_sample_images.py --count 30

사용법:
    set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
    python tests/phase6_ui_test.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
IMAGES_DIR = ROOT / "tests" / "sample" / "images"

passed: list[str] = []
failed: list[str] = []
made: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    print(f"[{'  OK  ' if ok else ' FAIL '}] {name}" + (f"   — {detail}" if detail else ""))
    return bool(ok)


def api(path: str, method: str = "GET", body: dict | None = None, timeout: int = 600):
    url = BASE + urllib.parse.quote(path, safe="/?&=.:%-")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read().decode("utf-8")
    return json.loads(raw) if raw else None


def dismiss_coach(page) -> None:
    for sel in ("#coach", "#shortcuts"):
        box = page.locator(sel)
        if box.count() and box.is_visible():
            close = page.locator(f"{sel} button.btn-primary")
            if close.count():
                close.first.click()
            else:
                page.evaluate(f"document.querySelector('{sel}').hidden = true")
            page.wait_for_timeout(150)


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright 가 설치되어 있지 않습니다.  python -m pip install playwright")
    sys.exit(2)

photos = sorted(IMAGES_DIR.glob("*"))[:6]
if len(photos) < 6:
    print(f"시험용 사진이 모자랍니다: {IMAGES_DIR}")
    print("  python tools/make_sample_images.py --count 30")
    sys.exit(1)

project = api("/api/projects", "POST",
              {"name": "화면점검_사진", "image_paths": [str(p) for p in photos], "mode": "video"})
pid = project["id"]
made.append(pid)
project["segments"] = [
    {"id": "s1", "start": 0.5, "end": 3.0, "text": "첫 줄"},
    {"id": "s2", "start": 3.0, "end": 6.0, "text": "둘째 줄"},
]
project["output"] = {"aspect": "9:16", "fit": "crop",
                     "focus_x": 50.0, "focus_y": 50.0, "pad_blur": True}
api(f"/api/projects/{pid}", "PUT", project)
print(f"점검용 사진 프로젝트: {pid}  (사진 {len(photos)}장)\n")

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
        page.wait_for_function(
            "document.querySelector('#player-img') && "
            "document.querySelector('#player-img').naturalWidth > 0", timeout=20000)
        page.wait_for_timeout(400)

        # ══ 그림이 실제로 보이는가 ═══════════════════════════════
        print("=== 사진이 미리보기에 나오는가 ===")
        check("사진 층(<img>)이 화면에 보인다",
              page.locator("#player-img").is_visible())
        check("'영상이 없는 프로젝트입니다' 안내가 사라졌다",
              not page.locator("#no-video").is_visible())
        first_src = page.locator("#player-img").get_attribute("src")
        check("첫 사진이 걸려 있다", "/image/0" in (first_src or ""), first_src or "")

        # ══ 왼쪽 사진 목록 ═══════════════════════════════════════
        print("\n=== 왼쪽 [사진] 칸 ===")
        check("사진 칸이 보인다", page.locator("#grp-photos").is_visible())
        check(f"목록에 사진 {len(photos)}장이 줄지어 있다",
              page.locator("#photo-list .photo-item").count() == len(photos),
              f"{page.locator('#photo-list .photo-item').count()}줄")
        summary = page.locator("#photo-summary").inner_text()
        check("전체 길이를 알려 준다", "전체" in summary, summary)

        # ══ 재생하면 시간이 흐르고 사진이 바뀌는가 ════════════════
        print("\n=== 재생: 시간이 흐르고 그 시각의 사진이 나오는가 ===")
        page.wait_for_function("document.querySelector('#player').duration > 0", timeout=20000)
        total = page.evaluate("document.querySelector('#player').duration")
        check("소리가 없어도 시계가 생겼다 (재생 길이가 잡힌다)",
              abs(total - len(photos) * 3.0) < 0.5, f"{total:.2f}초 (사진 {len(photos)}장×3초)")

        page.evaluate("document.querySelector('#player').currentTime = 0")
        page.locator("#btn-play").click()
        page.wait_for_timeout(1500)
        moving = page.evaluate("document.querySelector('#player').currentTime")
        check("재생을 누르니 시간이 흐른다", moving > 0.4, f"{moving:.2f}초")
        page.locator("#btn-play").click()   # 멈춤

        # 시각을 옮기면 그 시각의 사진으로 바뀌는가 (3초마다 다음 장)
        swaps = []
        for at, want_index in ((1.0, 0), (7.0, 2), (16.0, 5)):
            page.evaluate(f"document.querySelector('#player').currentTime = {at}")
            page.wait_for_timeout(500)
            src = page.locator("#player-img").get_attribute("src") or ""
            swaps.append((at, want_index, src))
            check(f"{at:.0f}초로 옮기면 {want_index + 1}번째 사진이 나온다",
                  src.endswith(f"/image/{want_index}"), src.split("/")[-1])

        # ══ 화면비를 바꾸면 틀이 실제로 바뀌는가 ══════════════════
        print("\n=== 화면비를 바꾸면 틀이 바뀌는가 ===")
        seen = {}
        for aspect in ("9:16", "16:9", "1:1"):
            page.locator(f".aspect-btn[data-aspect='{aspect}']").click()
            page.wait_for_timeout(400)
            box = page.locator("#fg-window").bounding_box()
            seen[aspect] = (round(box["width"]), round(box["height"])) if box else None
            check(f"{aspect} 를 고르면 틀이 그려진다",
                  bool(box) and box["width"] > 10 and box["height"] > 10,
                  f"{seen[aspect]}")
        ratios = {a: (v[0] / v[1] if v else 0) for a, v in seen.items()}
        check(
            "세 화면비의 틀 모양이 서로 다르다",
            len({round(r, 2) for r in ratios.values()}) == 3,
            " · ".join(f"{a} = {r:.2f}" for a, r in ratios.items()),
        )
        check(
            "고른 화면비와 틀의 모양이 실제로 같다",
            abs(ratios["9:16"] - 9 / 16) < 0.03 and abs(ratios["16:9"] - 16 / 9) < 0.05
            and abs(ratios["1:1"] - 1.0) < 0.03,
            " · ".join(f"{a} = {r:.2f}" for a, r in ratios.items()),
        )
        # 잘리는 부분이 어둡게 덮이는가 (틀 바깥을 덮는 그림자가 살아 있는지)
        shadow = page.locator("#fg-window").evaluate("el => getComputedStyle(el).boxShadow")
        check("틀 바깥(잘릴 부분)이 어둡게 덮인다", "rgba" in shadow and "9999" in shadow,
              shadow[:60])

        # 캔버스가 화면비를 따라 바뀌었는가 (내보낼 크기가 곧 이 값이다)
        page.locator(".aspect-btn[data-aspect='9:16']").click()
        page.wait_for_timeout(300)
        canvas = page.evaluate("JSON.stringify(project.canvas)")
        check("화면비를 바꾸면 내보낼 크기(캔버스)도 따라 바뀐다",
              json.loads(canvas) == {"width": 1080, "height": 1920}, canvas)

        # ══ 자막을 마우스로 끌 수 있는가 ══════════════════════════
        print("\n=== 자막을 마우스로 끌 수 있는가 ===")
        page.evaluate("document.querySelector('#player').currentTime = 1.0")
        page.wait_for_timeout(400)
        before_pos = json.loads(page.evaluate("JSON.stringify(project.style.position)"))
        overlay = page.locator("#overlay")
        box = overlay.bounding_box()
        check("지금 자막이 화면에 보인다", bool(box) and overlay.inner_text().strip() != "",
              overlay.inner_text().strip())
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2 - 80, steps=10)
        page.mouse.up()
        page.wait_for_timeout(400)
        after_pos = json.loads(page.evaluate("JSON.stringify(project.style.position)"))
        check("자막이 마우스를 따라 움직였다",
              abs(after_pos["y"] - before_pos["y"]) > 1.0,
              f"y {before_pos['y']} → {after_pos['y']}")

        check("화면에서 자바스크립트 오류가 나지 않았다", not errors,
              " / ".join(errors[:2]))

        # 끌어 놓은 자리를 저장해 둔다 — 아래에서 내보낸 영상과 대조한다
        page.evaluate("saveNow()")
        page.wait_for_timeout(800)
        browser.close()

    # ══ 미리보기에서 끈 자리와 내보낸 영상의 자리가 같은가 ══════════
    #
    # 이 프로젝트에서 가장 비싼 결함 유형이다. 화면에서 잘 보이는데 결과물에는
    # 자막이 없거나 딴 곳에 있는 상태 (438픽셀 어긋난 적이 있다).
    print("\n=== 끈 자리와 내보낸 영상의 자리가 같은가 ===")
    saved = api(f"/api/projects/{pid}")
    want_y = float(saved["style"]["position"]["y"])

    job = api(f"/api/projects/{pid}/render", "POST", {"kind": "burn"})["job_id"]
    import time as _time
    for _ in range(900):
        info = api(f"/api/jobs/{job}")
        if info["status"] == "done":
            break
        if info["status"] in ("error", "cancelled"):
            raise RuntimeError(info.get("message") or info["status"])
        _time.sleep(0.7)
    out = Path(info["result"]["path"])
    height = int(info["result"]["height"])

    # 자막이 있는 영상과 **자막 글만 비운 영상**을 같은 설정으로 각각 만들어
    # 밝은 픽셀의 무게중심을 비교한다. 배경이 밝아도 속지 않는다.
    blank = api(f"/api/projects/{pid}")
    blank["segments"] = [dict(s, text="") for s in blank["segments"]]
    blank["name"] = blank["name"] + "_빈자막"
    api(f"/api/projects/{pid}", "PUT", blank)
    job2 = api(f"/api/projects/{pid}/render", "POST", {"kind": "burn"})["job_id"]
    for _ in range(900):
        info2 = api(f"/api/jobs/{job2}")
        if info2["status"] == "done":
            break
        if info2["status"] in ("error", "cancelled"):
            raise RuntimeError(info2.get("message") or info2["status"])
        _time.sleep(0.7)
    out_blank = Path(info2["result"]["path"])

    def frame_gray(path: Path, at: float, w: int, h: int) -> bytes:
        res = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(path),
             "-frames:v", "1", "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, timeout=180,
        )
        return res.stdout

    W, H = 108, 192
    a = frame_gray(out, 1.0, W, H)
    b = frame_gray(out_blank, 1.0, W, H)
    if len(a) < W * H or len(b) < W * H:
        check("자막 픽셀의 무게중심을 잴 수 있다", False, "프레임을 읽지 못했다")
    else:
        total = 0.0
        weighted = 0.0
        for row in range(H):
            for col in range(W):
                diff = abs(a[row * W + col] - b[row * W + col])
                if diff > 24:                     # 자막 글자 때문에 생긴 차이만 센다
                    total += diff
                    weighted += diff * row
        if total <= 0:
            check("내보낸 영상에 자막 글자가 실제로 들어 있다", False, "차이 픽셀 0개")
        else:
            check("내보낸 영상에 자막 글자가 실제로 들어 있다", True, f"차이 무게 {int(total)}")
            got_y = (weighted / total) / H * 100.0
            check(
                "끈 자리와 내보낸 영상의 자막 자리가 1% 이내로 같다",
                abs(got_y - want_y) <= 1.0,
                f"화면에서 {want_y:.2f}% · 영상에서 {got_y:.2f}% (차이 {abs(got_y - want_y):.2f}%)",
            )

    # ══════════════════════════════════════════════════════════
    # 단계 5 — 음원 영상을 화면에서 실제로 다뤄 본다
    # ══════════════════════════════════════════════════════════
    print("\n=== 음원 영상: 소리 · 두드려 맞추기 · 안내 문구 ===")
    song = ROOT / "tests" / "sample" / "sample_song.mp3"
    if not song.is_file():
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=12",
             "-c:a", "libmp3lame", "-b:a", "128k", str(song)],
            check=True, timeout=180,
        )

    mp = api("/api/projects", "POST",
             {"name": "화면점검_음원", "audio_path": str(song), "mode": "video"})
    mpid = mp["id"]
    made.append(mpid)
    mp["images"] = [
        {"id": f"i{i + 1:03d}", "path": str(p), "duration": 3.0, "seg_id": None}
        for i, p in enumerate(photos[:3])
    ]
    mp["segments"] = [
        {"id": "s1", "start": 0.0, "end": 4.0, "text": "가사 첫 줄"},
        {"id": "s2", "start": 4.0, "end": 8.0, "text": "가사 둘째 줄"},
        {"id": "s3", "start": 8.0, "end": 12.0, "text": "가사 셋째 줄"},
    ]
    mp["canvas"] = {"width": 1080, "height": 1920}
    mp["output"] = {"aspect": "9:16", "fit": "crop", "focus_x": 50.0, "focus_y": 50.0,
                    "pad_blur": True}
    api(f"/api/projects/{mpid}", "PUT", mp)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errs: list[str] = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(f"{BASE}/?project={mpid}", wait_until="networkidle")
        dismiss_coach(page)
        page.wait_for_function("document.querySelector('#player').duration > 0", timeout=20000)
        page.wait_for_timeout(400)

        dur = page.evaluate("document.querySelector('#player').duration")
        check("mp3 를 넣으면 재생 길이가 잡힌다", abs(dur - 12.0) < 0.5, f"{dur:.2f}초")
        src = page.evaluate("document.querySelector('#player').getAttribute('src')")
        check("소리가 mp3 에서 나온다 (음원 주소가 물려 있다)", "/audio" in (src or ""), src or "")

        page.evaluate("document.querySelector('#player').currentTime = 0")
        page.locator("#btn-play").click()
        page.wait_for_timeout(1500)
        moved = page.evaluate("document.querySelector('#player').currentTime")
        muted = page.evaluate("document.querySelector('#player').muted")
        check("재생을 누르니 시간이 흐른다", moved > 0.4, f"{moved:.2f}초")
        check("소리가 꺼져 있지 않다", muted is False, f"muted={muted}")
        page.locator("#btn-play").click()

        # ── 두드려 맞추기: 실제로 스페이스바를 눌러 가사 시각을 찍는다 ──
        page.evaluate("""() => {
          project.segments = [
            {id: 's1', start: 0, end: 1, text: '가사 첫 줄'},
            {id: 's2', start: 1, end: 2, text: '가사 둘째 줄'},
            {id: 's3', start: 2, end: 3, text: '가사 셋째 줄'},
          ];
          renderAll();
        }""")
        page.wait_for_timeout(200)
        tap = page.locator("#btn-tapsync")
        check("[두드려 맞추기] 단추가 있다", tap.count() > 0)
        tap.click()
        page.wait_for_timeout(200)

        marks = []
        for at in (1.5, 5.0, 9.25):
            page.evaluate(f"document.querySelector('#player').currentTime = {at}")
            page.wait_for_timeout(250)
            page.keyboard.press("Space")
            page.wait_for_timeout(250)
            marks.append(at)
        page.wait_for_timeout(300)
        starts = json.loads(page.evaluate("JSON.stringify(project.segments.map(s => s.start))"))
        close = all(abs(starts[i] - marks[i]) < 0.35 for i in range(3))
        check(
            "스페이스바로 가사 3줄의 시작 시각을 찍을 수 있다",
            close,
            f"누른 시각 {marks} → 찍힌 시각 {starts}",
        )

        # ── 사진 수와 가사 줄 수가 다를 때 미리 알려 주는가 ──
        page.evaluate("""() => {
          project.images.push({id: 'iX', path: project.images[0].path, duration: 3, seg_id: null});
          afterPhotosChanged();
        }""")
        page.locator("#btn-photo-pair").click()
        page.wait_for_timeout(400)
        warn = page.locator("#photo-warning")
        text = warn.inner_text() if warn.count() and warn.is_visible() else ""
        check(
            "사진 수와 가사 줄 수가 다르면 무슨 일이 벌어지는지 한국어로 알려 준다",
            warn.is_visible() and "사진" in text and "가사" in text,
            text.replace("\n", " ")[:110],
        )

        # 짝지으면 목록에 어느 가사에 붙었는지 보인다
        first_row = page.locator("#photo-list .photo-item .photo-name").first.inner_text()
        check("사진 목록에 어느 가사 줄에 붙었는지 보인다", "♪" in first_row, first_row[:40])

        check("음원 화면에서 자바스크립트 오류가 나지 않았다", not errs, " / ".join(errs[:2]))
        browser.close()

finally:
    for p in made:
        try:
            api(f"/api/projects/{p}", "DELETE")
        except Exception:
            pass

print("\n" + "=" * 66)
print(f"  통과 {len(passed)}개 · 실패 {len(failed)}개")
print("=" * 66)
for name in failed:
    print(f"  실패: {name}")
raise SystemExit(1 if failed else 0)
