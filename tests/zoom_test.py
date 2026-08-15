"""화면 확대(잘라낼 사각형의 크기·위치) 점검.

사용법:
    python tests/zoom_test.py          서버를 띄우지 않아도 된다 (계산만 검사한다)

이 점검이 확인하려는 것 — `docs/DESIGN_effects_and_zoom.md` 9절의 수용 기준:
  · T1  화면(app.js)과 서버(framing.py)의 계산이 zoom 을 넣어도 한 픽셀도 안 어긋나는가
  · T2  확대하면 잘라내는 사각형이 실제로 작아지고, **출력 크기는 그대로**인가
  · T3  축소하면 여백을 채우는 필터가 들어가는가
  · T4  화질 지표(sharpness)가 실제 계산으로 나오는가
  · T9  zoom 이 없는 옛 프로젝트가 지금까지와 똑같이 동작하는가
  · T11 확대한 뒤 **가로·세로 위치가 둘 다** 움직이는가 (한쪽 축이 잠기면 안 된다)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# 윈도우 명령창은 cp949라 그냥 출력하면 한글이 깨진다 (memory/windows-console-encoding.md)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import framing  # noqa: E402

passed: list[str] = []
failed: list[str] = []
skipped: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    mark = "  OK  " if ok else " FAIL "
    print(f"[{mark}] {name}" + (f"   — {detail}" if detail else ""))
    return ok


def frame(sw: int, sh: int, **conf) -> dict:
    """가로 영상을 세로 9:16 으로 자르는 기본 설정에 원하는 값만 얹는다."""
    base = {"aspect": "9:16", "fit": "crop", "focus_x": 50.0, "focus_y": 50.0, "pad_blur": True}
    base.update(conf)
    return framing.resolve(sw, sh, base)


# ══════════════════════════════════════════════════════════════
# 1. 값 다듬기 — 사용자가 보내는 값이므로 경계에서 한 번 거른다
# ══════════════════════════════════════════════════════════════
print("\n=== 1. zoom 값 다듬기 ===")

conf = framing.normalize({})
check("zoom 을 안 보내면 1.0(확대 없음)이 된다",
      conf.get("zoom") == 1.0, f"실제 {conf.get('zoom')!r}")

check("상한을 넘기면 2.0 으로 깎인다",
      framing.normalize({"zoom": 9.0})["zoom"] == 2.0,
      f"실제 {framing.normalize({'zoom': 9.0}).get('zoom')!r}")

check("하한을 밑돌면 0.5 로 올라온다",
      framing.normalize({"zoom": 0.01})["zoom"] == 0.5,
      f"실제 {framing.normalize({'zoom': 0.01}).get('zoom')!r}")

check("숫자가 아닌 값을 보내면 1.0 으로 되돌린다",
      framing.normalize({"zoom": "많이"})["zoom"] == 1.0,
      f"실제 {framing.normalize({'zoom': '많이'}).get('zoom')!r}")


# ══════════════════════════════════════════════════════════════
# 2. T2 — 확대하면 사각형이 작아지고 출력 크기는 그대로
# ══════════════════════════════════════════════════════════════
print("\n=== 2. T2: 확대 ===")

one = frame(1280, 720)
two = frame(1280, 720, zoom=2.0)

check("확대해도 출력 영상 크기는 똑같다",
      (one["width"], one["height"]) == (two["width"], two["height"]),
      f"1.0배 {one['width']}x{one['height']} / 2.0배 {two['width']}x{two['height']}")

check("2.0배로 확대하면 잘라내는 가로가 절반이 된다",
      two["crop"] is not None and abs(two["crop"]["w"] - one["crop"]["w"] / 2) <= 2,
      f"1.0배 {one['crop']['w']}px → 2.0배 {two['crop']['w'] if two['crop'] else None}px")

check("2.0배로 확대하면 잘라내는 세로도 절반이 된다",
      two["crop"] is not None and abs(two["crop"]["h"] - one["crop"]["h"] / 2) <= 2,
      f"1.0배 {one['crop']['h']}px → 2.0배 {two['crop']['h'] if two['crop'] else None}px")

check("확대하면 늘리는 필터(scale)가 들어간다",
      "scale=" in (two["filter"] or ""), f"필터: {two['filter']}")

check("확대하지 않으면 늘리는 필터가 들어가지 않는다",
      "scale=" not in (one["filter"] or ""), f"필터: {one['filter']}")


# ══════════════════════════════════════════════════════════════
# 3. T3 — 축소하면 여백이 생긴다
# ══════════════════════════════════════════════════════════════
print("\n=== 3. T3: 축소 ===")

half = frame(1280, 720, zoom=0.5)

check("축소해도 출력 영상 크기는 똑같다",
      (half["width"], half["height"]) == (one["width"], one["height"]),
      f"0.5배 {half['width']}x{half['height']} / 1.0배 {one['width']}x{one['height']}")

check("축소하면 남는 자리를 채우는 필터가 들어간다",
      "pad=" in (half["filter"] or "") or "overlay" in (half["filter"] or ""),
      f"필터: {half['filter']}")


# ══════════════════════════════════════════════════════════════
# 4. T4 — 화질 지표
# ══════════════════════════════════════════════════════════════
print("\n=== 4. T4: 화질 지표 ===")

check("확대하지 않으면 화질 지표가 1.0 이다",
      abs(one.get("sharpness", 0) - 1.0) < 0.01, f"실제 {one.get('sharpness')!r}")

check("2.0배로 확대하면 화질 지표가 0.5 안팎으로 떨어진다",
      0.45 <= two.get("sharpness", 0) <= 0.55, f"실제 {two.get('sharpness')!r}")

check("화질 지표는 확대할수록 단조롭게 낮아진다",
      frame(1280, 720, zoom=1.2)["sharpness"]
      > frame(1280, 720, zoom=1.6)["sharpness"]
      > frame(1280, 720, zoom=2.0)["sharpness"],
      f"1.2배 {frame(1280, 720, zoom=1.2)['sharpness']} / "
      f"1.6배 {frame(1280, 720, zoom=1.6)['sharpness']} / "
      f"2.0배 {frame(1280, 720, zoom=2.0)['sharpness']}")


# ══════════════════════════════════════════════════════════════
# 5. T11 — 확대한 뒤 가로·세로가 **둘 다** 움직여야 한다
#    확대 전에는 세로로 움직일 자리가 없다. 확대하면 생긴다.
#    한쪽 축이 잠기면 오류 없이 "위아래로 안 움직이는" 상태가 된다.
# ══════════════════════════════════════════════════════════════
print("\n=== 5. T11: 확대 뒤 두 축이 모두 움직이는가 ===")

left = frame(1280, 720, zoom=1.6, focus_x=0)
right = frame(1280, 720, zoom=1.6, focus_x=100)
check("확대 상태에서 가로 위치를 바꾸면 잘라내는 자리가 움직인다",
      left["crop"]["x"] != right["crop"]["x"],
      f"0% → x={left['crop']['x']} / 100% → x={right['crop']['x']}")

top = frame(1280, 720, zoom=1.6, focus_y=0)
bottom = frame(1280, 720, zoom=1.6, focus_y=100)
check("확대 상태에서 세로 위치를 바꾸면 잘라내는 자리가 움직인다",
      top["crop"]["y"] != bottom["crop"]["y"],
      f"0% → y={top['crop']['y']} / 100% → y={bottom['crop']['y']}")

flat_top = frame(1280, 720, focus_y=0)
flat_bottom = frame(1280, 720, focus_y=100)
check("확대하지 않으면 세로로는 움직일 자리가 없다 (지금까지의 동작)",
      flat_top["crop"]["y"] == flat_bottom["crop"]["y"] == 0,
      f"0% → y={flat_top['crop']['y']} / 100% → y={flat_bottom['crop']['y']}")


# ══════════════════════════════════════════════════════════════
# 6. T9 — 옛 프로젝트가 그대로 열린다
# ══════════════════════════════════════════════════════════════
print("\n=== 6. T9: 옛 프로젝트 ===")

for aspect in ["source", "16:9", "9:16", "1:1"]:
    for fit in ["crop", "pad"]:
        old = framing.resolve(1920, 1080, {"aspect": aspect, "fit": fit,
                                           "focus_x": 50.0, "focus_y": 50.0, "pad_blur": True})
        new = framing.resolve(1920, 1080, {"aspect": aspect, "fit": fit, "zoom": 1.0,
                                           "focus_x": 50.0, "focus_y": 50.0, "pad_blur": True})
        if (old["width"], old["height"], old["filter"]) != (new["width"], new["height"], new["filter"]):
            check(f"zoom 없는 옛 설정({aspect}/{fit})이 zoom=1.0 과 같다", False,
                  f"{old['width']}x{old['height']} {old['filter']} vs {new['width']}x{new['height']} {new['filter']}")
            break
else:
    check("zoom 없는 옛 설정 8가지가 모두 zoom=1.0 과 똑같이 나온다", True)


# ══════════════════════════════════════════════════════════════
# 7. T1 — 화면(app.js)과 서버(framing.py)의 계산 대조
#    app.js 를 사본 없이 그대로 실행한다. 베껴 두면 베낀 쪽만 맞는 함정에 빠진다.
# ══════════════════════════════════════════════════════════════
print("\n=== 7. T1: 화면과 서버의 계산 대조 (zoom 포함) ===")

CASES = []
for sw, sh in [(1920, 1080), (1280, 720), (1080, 1920), (640, 480), (1000, 1000)]:
    for aspect in ["source", "16:9", "9:16", "1:1"]:
        for fit in ["crop", "pad"]:
            for fx, fy in [(0, 0), (50, 50), (100, 100), (25, 73)]:
                for zoom in [0.5, 0.8, 1.0, 1.3, 2.0]:
                    CASES.append((sw, sh, aspect, fit, fx, fy, zoom))

node = shutil.which("node")
if not node:
    check("node 로 app.js 계산을 확인할 수 있다", False,
          "node 가 없어 화면 쪽 계산을 대조하지 못했습니다 (서버 쪽만 확인함)")
else:
    src = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    # 경우의 수가 많아 명령줄로 넘기면 윈도우의 길이 한계(약 3만 자)에 걸린다.
    # 파일로 건넨다.
    harness = r"""
const cases = JSON.parse(require("fs").readFileSync(process.argv[2], "utf-8"));
const out = cases.map(([w, h, aspect, fit, fx, fy, zoom]) => {
  const r = resolveFraming(w, h, {aspect, fit, focus_x: fx, focus_y: fy, pad_blur: true, zoom});
  return {width: r.width, height: r.height, changed: r.changed,
          crop: r.crop ? [r.crop.x, r.crop.y, r.crop.w, r.crop.h] : null};
});
console.log(JSON.stringify(out));
"""
    shim = r"""
const FAKE = new Proxy(function () {}, {
  get(_t, p) {
    if (p === Symbol.toPrimitive || p === "toString") return () => "";
    if (p === "length") return 0;
    if (p === "hidden" || p === "checked" || p === "disabled" || p === "paused") return false;
    if (p === "value" || p === "textContent" || p === "innerHTML" || p === "title") return "";
    if (p === "videoWidth" || p === "videoHeight" || p === "currentTime" || p === "duration") return 0;
    if (p === "forEach" || p === "map" || p === "filter") return () => [];
    return FAKE;
  },
  set() { return true; },
  apply() { return FAKE; },
  has() { return true; },
});
globalThis.window = globalThis;
globalThis.self = globalThis;
globalThis.document = {
  readyState: "complete",
  addEventListener() {}, removeEventListener() {},
  querySelector() { return FAKE; }, querySelectorAll() { return []; },
  getElementById() { return FAKE; }, createElement() { return FAKE; },
  body: FAKE, documentElement: FAKE,
};
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.navigator = { serviceWorker: { register: () => Promise.reject(new Error("no sw")) } };
globalThis.history = { replaceState() {} };
globalThis.location = { search: "", href: "", pathname: "/" };
globalThis.fetch = () => Promise.reject(new Error("no network in test"));
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.requestAnimationFrame = () => 0;
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
process.on("unhandledRejection", () => {});
"""
    tmp = ROOT / "tests" / "_zoom_harness.js"
    cases_file = ROOT / "tests" / "_zoom_cases.json"
    tmp.write_text(shim + src + harness, encoding="utf-8")
    cases_file.write_text(json.dumps(CASES), encoding="utf-8")
    try:
        proc = subprocess.run(
            [node, str(tmp), str(cases_file)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        if proc.returncode != 0:
            check("app.js 의 화면비 계산을 실행할 수 있다", False, (proc.stderr or "")[:300])
        else:
            js_results = json.loads(proc.stdout)
            mismatches = []
            for (sw, sh, aspect, fit, fx, fy, zoom), js in zip(CASES, js_results):
                py = framing.resolve(sw, sh, {
                    "aspect": aspect, "fit": fit, "focus_x": fx, "focus_y": fy,
                    "pad_blur": True, "zoom": zoom,
                })
                py_crop = ([py["crop"]["x"], py["crop"]["y"], py["crop"]["w"], py["crop"]["h"]]
                           if py["crop"] else None)
                if (py["width"], py["height"], py["changed"], py_crop) != (
                        js["width"], js["height"], js["changed"], js["crop"]):
                    mismatches.append(
                        f"{sw}x{sh} {aspect}/{fit}/focus({fx},{fy})/zoom{zoom}: "
                        f"서버 {py['width']}x{py['height']}{py_crop} vs 화면 {js['width']}x{js['height']}{js['crop']}"
                    )
            check(f"화면과 서버의 계산이 {len(CASES)}가지 경우에서 모두 같다",
                  not mismatches,
                  "전부 일치" if not mismatches else f"{len(mismatches)}건 불일치: " + "; ".join(mismatches[:3]))
    finally:
        tmp.unlink(missing_ok=True)
        cases_file.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════
# 8. T2·T3 실물 — 실제로 영상을 만들어 확인한다
#    계산이 맞아도 FFmpeg 이 다르게 동작하면 소용없다. 이 프로젝트의 결함 대부분이
#    "오류 없이 틀린 결과"였으므로 **만든 파일을 직접 재서** 판정한다.
#    서버가 켜져 있어야 하며, 없으면 건너뛴 것으로 **분명히 표시**한다.
# ══════════════════════════════════════════════════════════════
print("\n=== 8. T2·T3: 실제로 만든 영상 측정 ===")

BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
SAMPLE = ROOT / "tests" / "sample" / "sample_10s.mp4"


def api(path: str, method: str = "GET", body: dict | None = None, timeout: int = 300):
    url = BASE + urllib.parse.quote(path, safe="/?&=.:%-")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8") or "{}")


def run_job(job_id: str, limit: float = 600.0) -> dict:
    deadline = time.time() + limit
    while time.time() < deadline:
        info = api(f"/api/jobs/{job_id}")
        if info["status"] == "done":
            return info.get("result") or {}
        if info["status"] in ("error", "cancelled"):
            raise RuntimeError(info.get("message") or info["status"])
        time.sleep(1.0)
    raise TimeoutError("작업이 제한 시간 안에 끝나지 않았습니다.")


def probe_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    stream = json.loads(out.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def psnr(a: Path, b: Path) -> float | None:
    """두 영상이 얼마나 닮았는지. 값이 클수록 닮았다 (완전히 같으면 inf)."""
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(a), "-i", str(b), "-lavfi", "psnr", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    hit = re.search(r"average:(inf|[0-9.]+)", out.stderr or "")
    if not hit:
        return None
    return float("inf") if hit.group(1) == "inf" else float(hit.group(1))


try:
    api("/api/health", timeout=5)
    server_up = True
except Exception as exc:
    server_up = False
    print(f"      서버에 연결하지 못했습니다 ({BASE}) — 실물 점검을 **건너뜁니다**: {exc}")
    print("      python -m app --port 8766 으로 띄우고 MOVIEFIT_TEST_URL 을 맞춘 뒤 다시 실행하세요.")
    skipped.append("T2·T3 실물 점검 (서버 없음)")

if server_up and not SAMPLE.is_file():
    server_up = False
    print(f"      샘플 영상이 없어 **건너뜁니다**: {SAMPLE}")
    print("      python tools/make_sample.py 를 먼저 실행하세요.")
    skipped.append("T2·T3 실물 점검 (샘플 영상 없음)")

if server_up:
    pid = ""
    try:
        proj = api("/api/projects", "POST",
                   {"name": "확대점검", "video_path": str(SAMPLE), "mode": "video"})
        pid = proj["id"]
        # 자막은 글자를 비워 둔다. 자막은 잘라내기 **뒤에** 새겨지므로 확대해도 커지지 않는데,
        # 아래 '가운데를 확대한 것과 닮았는가' 비교에서는 글자까지 커져 버려 판정을 망친다.
        proj["segments"] = [{"id": "s1", "start": 0.2, "end": 1.8, "text": ""}]

        made: dict[float, Path] = {}
        for zoom in (1.0, 2.0):
            proj["output"] = {"aspect": "9:16", "fit": "crop", "focus_x": 50, "focus_y": 50,
                              "pad_blur": True, "zoom": zoom}
            api(f"/api/projects/{pid}", "PUT", proj)
            job = api(f"/api/projects/{pid}/render", "POST",
                      {"kind": "preview", "preview_seconds": 2})
            made[zoom] = Path(run_job(job["job_id"])["path"])

        size_one, size_two = probe_size(made[1.0]), probe_size(made[2.0])
        check("확대해서 만든 영상의 크기가 확대 전과 똑같다",
              size_one == size_two, f"1.0배 {size_one[0]}×{size_one[1]} / 2.0배 {size_two[0]}×{size_two[1]}")

        want = api(f"/api/system/framing?w=1280&h=720&aspect=9:16&fit=crop&zoom=2.0")
        check("확대해서 만든 영상의 크기가 서버 계산과 같다",
              size_two == (want["width"], want["height"]),
              f"실제 {size_two[0]}×{size_two[1]} / 계산 {want['width']}×{want['height']}")

        # 화면이 실제로 달라졌는가, 그리고 그 달라짐이 **확대**가 맞는가.
        # 1.0배 결과의 한가운데를 두 배로 키운 것이 2.0배 결과와 훨씬 닮아야 한다.
        magnified = made[1.0].with_name("_zoom_ref.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(made[1.0]),
             "-vf", f"crop=iw/2:ih/2,scale={size_two[0]}:{size_two[1]}",
             "-c:v", "libx264", "-preset", "ultrafast", "-an", str(magnified)],
            check=True, timeout=180,
        )
        raw = psnr(made[1.0], made[2.0])
        ref = psnr(magnified, made[2.0])
        magnified.unlink(missing_ok=True)

        check("확대하면 화면이 실제로 달라진다",
              raw is not None and raw < 30.0, f"닮음 지표 {raw} (낮을수록 다름)")
        check("그 달라짐이 '가운데를 두 배로 키운 것'과 일치한다 (진짜 확대가 맞다)",
              raw is not None and ref is not None and ref > raw + 3.0,
              f"가운데확대 대조 {ref} vs 원본 대조 {raw} (클수록 닮음)")

        # 축소 — 여백이 생겨야 한다. 가장자리 세로줄이 가운데보다 어두워지는지 잰다.
        proj["output"] = {"aspect": "9:16", "fit": "crop", "focus_x": 50, "focus_y": 50,
                          "pad_blur": False, "zoom": 0.5}
        api(f"/api/projects/{pid}", "PUT", proj)
        job = api(f"/api/projects/{pid}/render", "POST", {"kind": "preview", "preview_seconds": 2})
        small = Path(run_job(job["job_id"])["path"])
        check("축소해서 만든 영상의 크기도 확대 전과 똑같다",
              probe_size(small) == size_one, f"0.5배 {probe_size(small)} / 1.0배 {size_one}")

        # metadata=print 는 값을 **기록(로그)** 으로 내보낸다. -v error 로 막으면 값이 사라진다.
        edge = subprocess.run(
            ["ffmpeg", "-v", "info", "-ss", "1", "-i", str(small), "-frames:v", "1",
             "-vf", "crop=iw:ih*0.08:0:0,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
             "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        hit = re.search(r"YAVG=([0-9.]+)", edge.stdout + edge.stderr)
        top_avg = float(hit.group(1)) if hit else None
        check("축소하면 위쪽에 검은 여백이 생긴다",
              top_avg is not None and top_avg < 20.0,
              f"맨 위 8% 띠의 밝기 {top_avg} (검정이면 16 안팎)")

    except Exception as exc:
        check("실제로 만든 영상으로 확대를 확인한다", False, f"{type(exc).__name__}: {exc}")
    finally:
        if pid:
            try:
                api(f"/api/projects/{pid}", "DELETE")
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 62)
print(f"  통과 {len(passed)}개 · 실패 {len(failed)}개"
      + (f" · 건너뜀 {len(skipped)}개" if skipped else ""))
for name in skipped:
    print(f"   · 건너뜀: {name}")
if failed:
    print("\n  실패한 항목:")
    for name in failed:
        print(f"   - {name}")
print("=" * 62)
sys.exit(1 if failed else 0)
