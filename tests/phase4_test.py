"""기능 4건(F-A 화면비 전환 / F-B 위치 화살표 / F-C 롱폼·숏폼 / F-D 저장됨 클릭) 점검.

사용법:
    1) 개발 서버를 띄운다      python -m app            (설치본이 8765를 쓰고 있으면 --port 8766)
    2) 이 파일을 실행한다      python tests/phase4_test.py
       (다른 포트면  set MOVIEFIT_TEST_URL=http://127.0.0.1:8766  을 먼저)

이 점검이 확인하려는 것 — "코드가 그렇게 되어 있다"가 아니라 "결과물이 실제로 그렇다":
  · 화면(app.js)과 서버(framing.py)의 화면비 계산이 **한 픽셀도 어긋나지 않는지**
  · 실제로 내보낸 mp4 파일의 **크기를 ffprobe로 재서** 의도한 화면비가 맞는지
  · 잘라낼 자리를 옮기면 결과 영상의 **그림이 실제로 달라지는지** (픽셀을 비교한다)
  · 화면비를 바꿔도 자막이 **잘려 나가지 않고** 영상 안에 남는지 (밝은 픽셀을 센다)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# 윈도우 명령창은 cp949라 그냥 출력하면 한글이 깨지거나 죽는다 (memory/windows-console-encoding.md)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 설치본이 8765를 쓰고 있으면 개발 서버를 다른 포트로 띄우고 여기로 겨냥한다.
#   예)  set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
SAMPLE = ROOT / "tests" / "sample" / "sample_10s.mp4"

passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    mark = "  OK  " if ok else " FAIL "
    print(f"[{mark}] {name}" + (f"   — {detail}" if detail else ""))
    return ok


def api(path: str, method: str = "GET", body: dict | None = None, timeout: int = 300):
    url = BASE + urllib.parse.quote(path, safe="/?&=.:%-")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read().decode("utf-8")
    return json.loads(raw) if raw else None


def get_text(path: str) -> str:
    with urllib.request.urlopen(BASE + path, timeout=20) as res:
        return res.read().decode("utf-8", "replace")


def probe_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    stream = json.loads(out.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def run_job(job_id: str, limit: float = 600.0) -> dict:
    """작업이 끝날 때까지 기다렸다가 결과를 돌려준다."""
    deadline = time.time() + limit
    while time.time() < deadline:
        info = api(f"/api/jobs/{job_id}")
        if info["status"] == "done":
            return info.get("result") or {}
        if info["status"] in ("error", "cancelled"):
            raise RuntimeError(info.get("message") or info["status"])
        time.sleep(1.0)
    raise TimeoutError("작업이 제한 시간 안에 끝나지 않았습니다.")


# ══════════════════════════════════════════════════════════════
# 1. 서버가 살아 있는가
# ══════════════════════════════════════════════════════════════
print("\n=== 1. 서버 확인 ===")
try:
    health = api("/api/health")
    check("서버가 응답한다", bool(health.get("ok")), f"버전 {health.get('version')}")
except Exception as exc:
    print(f"\n서버에 연결할 수 없습니다: {exc}")
    print(f"  겨냥한 주소: {BASE}")
    print("  1) 다른 창에서  python -m app  (또는 --port 8766) 을 먼저 실행하세요.")
    sys.exit(1)

if not SAMPLE.is_file():
    print(f"\n샘플 영상이 없습니다: {SAMPLE}")
    print("  python tools/make_sample.py 를 먼저 실행하세요.")
    sys.exit(1)

SRC_W, SRC_H = probe_size(SAMPLE)
print(f"      샘플 영상: {SRC_W}×{SRC_H}")


# ══════════════════════════════════════════════════════════════
# 2. F-C — 화면(app.js)과 서버(framing.py)의 계산이 같은가
#    두 곳에 같은 규칙을 두었으므로, 어긋나면 미리보기와 결과물이 달라진다.
# ══════════════════════════════════════════════════════════════
print("\n=== 2. F-C: 화면과 서버의 화면비 계산 대조 ===")

CASES = []
for sw, sh in [(1920, 1080), (1280, 720), (1080, 1920), (640, 480), (1000, 1000), (SRC_W, SRC_H)]:
    for aspect in ["source", "16:9", "9:16", "1:1"]:
        for fit in ["crop", "pad"]:
            for focus in [0, 25, 50, 73, 100]:
                CASES.append((sw, sh, aspect, fit, focus))

node = shutil.which("node")
if not node:
    check("node 로 app.js 계산을 확인할 수 있다", False,
          "node 가 없어 화면 쪽 계산을 대조하지 못했습니다 (서버 쪽만 확인함)")
else:
    # app.js 를 그대로 읽어 브라우저 밖에서 실행한다. 사본을 만들지 않으므로
    # "테스트용으로 베낀 코드만 맞다"는 함정에 빠지지 않는다.
    src = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    harness = r"""
const cases = JSON.parse(process.argv[2]);
const out = cases.map(([w, h, aspect, fit, focus]) => {
  const r = resolveFraming(w, h, {aspect, fit, focus_x: focus, focus_y: focus, pad_blur: true});
  return {width: r.width, height: r.height, changed: r.changed,
          crop: r.crop ? [r.crop.x, r.crop.y, r.crop.w, r.crop.h] : null};
});
console.log(JSON.stringify(out));
"""
    # 브라우저에만 있는 것들을 흉내 낸다. app.js 는 불러오자마자 화면을 연결하려 들기 때문에
    # "무엇을 물어봐도 자기 자신을 돌려주는 가짜 요소"를 하나 만들어 전부 그것으로 답한다.
    # 이렇게 해야 **실제 app.js 파일 그대로**를 실행할 수 있다 (계산식을 베껴 두면
    # 베낀 쪽만 맞고 진짜 화면은 틀린 상태를 못 잡는다).
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
    tmp = ROOT / "tests" / "_appjs_harness.js"
    tmp.write_text(shim + src + harness, encoding="utf-8")
    try:
        proc = subprocess.run(
            [node, str(tmp), json.dumps(CASES)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        if proc.returncode != 0:
            check("app.js 의 화면비 계산을 실행할 수 있다", False, (proc.stderr or "")[:300])
        else:
            js_results = json.loads(proc.stdout)
            from app.core import framing

            mismatches = []
            for (sw, sh, aspect, fit, focus), js in zip(CASES, js_results):
                py = framing.resolve(sw, sh, {
                    "aspect": aspect, "fit": fit,
                    "focus_x": focus, "focus_y": focus, "pad_blur": True,
                })
                py_crop = ([py["crop"]["x"], py["crop"]["y"], py["crop"]["w"], py["crop"]["h"]]
                           if py["crop"] else None)
                if (py["width"], py["height"], py["changed"], py_crop) != (
                        js["width"], js["height"], js["changed"], js["crop"]):
                    mismatches.append(
                        f"{sw}x{sh} {aspect}/{fit}/focus{focus}: "
                        f"서버 {py['width']}x{py['height']}{py_crop} vs 화면 {js['width']}x{js['height']}{js['crop']}"
                    )
            check(f"화면과 서버의 계산이 {len(CASES)}가지 경우에서 모두 같다",
                  not mismatches,
                  "전부 일치" if not mismatches else f"{len(mismatches)}건 불일치: " + "; ".join(mismatches[:3]))
    finally:
        tmp.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════
# 3. 서버 API 가 계산 결과를 돌려주는가
# ══════════════════════════════════════════════════════════════
print("\n=== 3. 화면비 계산 API ===")
r = api("/api/system/framing?w=1920&h=1080&aspect=9:16&fit=crop&focus_x=50")
check("1920×1080 을 9:16 으로 자르면 608×1080 이다",
      (r["width"], r["height"]) == (608, 1080), f"{r['width']}×{r['height']}")
check("가운데를 남긴다 (좌우로 656픽셀씩 잘라냄)",
      r["crop"]["x"] == 656, f"x={r['crop']['x']}")

r0 = api("/api/system/framing?w=1920&h=1080&aspect=9:16&fit=crop&focus_x=0")
r100 = api("/api/system/framing?w=1920&h=1080&aspect=9:16&fit=crop&focus_x=100")
check("왼쪽 끝을 고르면 x=0, 오른쪽 끝을 고르면 x=1312",
      (r0["crop"]["x"], r100["crop"]["x"]) == (0, 1312),
      f"{r0['crop']['x']} / {r100['crop']['x']}")

rp = api("/api/system/framing?w=1920&h=1080&aspect=9:16&fit=pad")
check("여백 채우기는 1080×1920 (쇼츠 표준 크기) 이다",
      (rp["width"], rp["height"]) == (1080, 1920), f"{rp['width']}×{rp['height']}")

rs = api("/api/system/framing?w=1920&h=1080&aspect=source")
check("원본 그대로면 화면을 손대지 않는다",
      rs["changed"] is False and rs["filter"] is None, f"changed={rs['changed']}")

rbad = api("/api/system/framing?w=1920&h=1080&aspect=말도안되는값&fit=엉터리")
check("이상한 값을 보내면 조용히 기본값으로 되돌린다",
      rbad["aspect"] == "source" and rbad["fit"] == "crop",
      f"aspect={rbad['aspect']} fit={rbad['fit']}")


# ══════════════════════════════════════════════════════════════
# 4. F-D — "저장됨" 이 누를 수 있는 단추인가
# ══════════════════════════════════════════════════════════════
print("\n=== 4. F-D: 저장됨 클릭 ===")
html = get_text("/")
appjs = get_text("/app.js")
css = get_text("/style.css")

check("저장 상태가 글자가 아니라 단추다",
      re.search(r'<button[^>]*id="save-state"', html) is not None)
check("단추를 누르면 저장이 실행되도록 연결되어 있다",
      '$("#save-state").addEventListener("click"' in appjs)
check("누르면 저장이 즉시 일어난다 (2초 자동 저장을 기다리지 않는다)",
      "saveNow({ flash: true })" in appjs and "clearTimeout(saveTimer)" in appjs)
check("마우스를 올리면 누를 수 있다는 것이 보인다",
      "cursor: pointer" in css.split(".save-state")[1][:400] if ".save-state" in css else False)
check("마지막 저장 시각을 알려 준다", "refreshSaveTip" in appjs and "마지막 저장" in appjs)


# ══════════════════════════════════════════════════════════════
# 5. F-B — 위치 화살표 단추
# ══════════════════════════════════════════════════════════════
print("\n=== 5. F-B: 자막 위치 화살표 ===")
for direction, arrow in [("up", "↑"), ("down", "↓"), ("left", "←"), ("right", "→")]:
    check(f"{arrow} 단추가 화면에 있다", f'data-nudge="{direction}"' in html)
check("한 번에 1%, Shift와 함께 누르면 5% 움직인다",
      "NUDGE_STEP = 1" in appjs and "NUDGE_STEP_BIG = 5" in appjs)
check("Shift 여부를 실제로 읽는다", "nudgePosition(btn.dataset.nudge, e.shiftKey)" in appjs)


# ══════════════════════════════════════════════════════════════
# 6. F-A — 화면비 단추 4종
# ══════════════════════════════════════════════════════════════
print("\n=== 6. F-A: 화면비 전환 단추 ===")
for aspect in ["source", "16:9", "9:16", "1:1"]:
    check(f"[{aspect}] 단추가 화면에 있다", f'data-aspect="{aspect}"' in html)
check("잘라내기 / 여백 채우기를 고를 수 있다",
      'data-fit="crop"' in html and 'data-fit="pad"' in html)
check("미리보기 틀을 마우스로 끌 수 있다", "wireFrameDrag" in appjs and "pointerdown" in appjs)


# ══════════════════════════════════════════════════════════════
# 7. F-C ⓑ — 실제로 내보낸 영상의 크기를 잰다 (가장 중요한 확인)
# ══════════════════════════════════════════════════════════════
print("\n=== 7. F-C ⓑ: 실제 내보내기 결과 측정 ===")
proj = api("/api/projects", "POST",
           {"name": "화면비점검", "video_path": str(SAMPLE), "mode": "video"})
pid = proj["id"]
print(f"      점검용 프로젝트: {pid}")

proj["segments"] = [
    {"id": "s1", "start": 0.2, "end": 2.0, "text": "가로 세로 시험"},
    {"id": "s2", "start": 2.2, "end": 4.0, "text": "자막이 남아 있는가"},
]
proj["style"] = dict(proj["style"], size=48)

EXPECT = {
    "source": (SRC_W, SRC_H),
    "9:16": None,    # 아래에서 서버 계산으로 채운다
    "1:1": None,
    "16:9": None,
}
for aspect in list(EXPECT):
    if EXPECT[aspect] is None:
        got = api(f"/api/system/framing?w={SRC_W}&h={SRC_H}&aspect={aspect}&fit=crop")
        EXPECT[aspect] = (got["width"], got["height"])

made: dict[str, Path] = {}
for aspect, fit in [("source", "crop"), ("9:16", "crop"), ("1:1", "crop"), ("9:16", "pad")]:
    proj["output"] = {"aspect": aspect, "fit": fit, "focus_x": 50, "focus_y": 50, "pad_blur": True}
    api(f"/api/projects/{pid}", "PUT", proj)

    job = api(f"/api/projects/{pid}/render", "POST", {"kind": "preview", "preview_seconds": 3})
    result = run_job(job["job_id"])
    out_path = Path(result["path"])

    if fit == "pad":
        want = api(f"/api/system/framing?w={SRC_W}&h={SRC_H}&aspect={aspect}&fit=pad")
        expect = (want["width"], want["height"])
    else:
        expect = EXPECT[aspect]

    actual = probe_size(out_path)
    check(f"{aspect} · {fit} 로 내보낸 파일이 실제로 {expect[0]}×{expect[1]} 이다",
          actual == expect, f"실제 {actual[0]}×{actual[1]}  ({out_path.name})")
    made[f"{aspect}/{fit}"] = out_path

    if aspect != "source":
        tag = aspect.replace(":", "-")
        check(f"{aspect} 결과물 이름으로 가로본·세로본을 구별할 수 있다",
              tag in out_path.name, out_path.name)


# ══════════════════════════════════════════════════════════════
# 8. 잘라낼 자리를 옮기면 결과 그림이 실제로 달라지는가
#    (설정이 저장만 되고 렌더링에 안 먹는 것을 잡기 위한 확인)
# ══════════════════════════════════════════════════════════════
print("\n=== 8. F-C ⓑ: 잘라낼 자리가 결과에 반영되는가 ===")


def first_frame_png(video: Path, dst: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
         "-i", str(video), "-frames:v", "1", str(dst)],
        capture_output=True, timeout=120, check=True,
    )
    return dst


shots = {}
for focus in (0, 100):
    proj["output"] = {"aspect": "9:16", "fit": "crop", "focus_x": focus, "focus_y": 50, "pad_blur": True}
    api(f"/api/projects/{pid}", "PUT", proj)
    job = api(f"/api/projects/{pid}/render", "POST", {"kind": "preview", "preview_seconds": 2})
    result = run_job(job["job_id"])
    shots[focus] = first_frame_png(Path(result["path"]),
                                   Path(result["path"]).with_name(f"focus{focus}.png"))

left_bytes = shots[0].read_bytes()
right_bytes = shots[100].read_bytes()
check("왼쪽 끝을 남길 때와 오른쪽 끝을 남길 때의 그림이 서로 다르다",
      left_bytes != right_bytes,
      f"왼쪽 {len(left_bytes)}바이트 / 오른쪽 {len(right_bytes)}바이트")


# ══════════════════════════════════════════════════════════════
# 9. 화면비를 바꿔도 자막이 살아 있는가
#    자르기가 자막보다 나중에 걸리면 자막이 통째로 잘려 나간다.
# ══════════════════════════════════════════════════════════════
print("\n=== 9. 화면비를 바꿔도 자막이 남아 있는가 ===")
# 자르기가 자막보다 **나중에** 걸리면 자막이 통째로 잘려 나간다.
#
# 주의: 결과물의 밝은 픽셀을 그냥 세면 안 된다. 영상 배경 자체가 밝으면 자막이 하나도
# 없어도 통과해 버린다(이 프로젝트가 이미 겪은 '동어반복 검증'이다). 그래서 **같은 화면비로
# 자막 글을 비운 영상을 한 번 더 만들어** 같은 시각의 프레임을 비교한다. 두 영상의 차이는
# 오직 자막뿐이므로, 밝은 픽셀이 늘어난 만큼이 실제로 새겨진 글자다.


def bright_pixels(video: Path, at: float = 1.0) -> int:
    """지정한 시각의 프레임에서 아주 밝은 픽셀 수를 센다."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
         "-ss", f"{at}", "-i", str(video), "-frames:v", "1",
         "-vf", "format=gray", "-f", "rawvideo", "-"],
        capture_output=True, timeout=120,
    )
    return sum(1 for b in out.stdout if b > 200)


for aspect, fit in [("source", "crop"), ("9:16", "crop"), ("1:1", "crop"), ("9:16", "pad")]:
    key = f"{aspect}/{fit}"
    proj["output"] = {"aspect": aspect, "fit": fit, "focus_x": 50, "focus_y": 50, "pad_blur": True}

    # (1) 자막 글이 있는 영상 — 7절에서 만든 것을 그대로 쓴다
    with_text = made[key]

    # (2) 똑같은 설정에 자막 글만 비운 영상
    blank = [dict(s, text="") for s in proj["segments"]]
    api(f"/api/projects/{pid}", "PUT", dict(proj, segments=blank))
    job = api(f"/api/projects/{pid}/render", "POST", {"kind": "preview", "preview_seconds": 3})
    without_text = Path(run_job(job["job_id"])["path"])
    api(f"/api/projects/{pid}", "PUT", proj)  # 자막을 되돌려 놓는다

    lit = bright_pixels(with_text, at=1.0)
    dark = bright_pixels(without_text, at=1.0)
    gained = lit - dark
    # 글자 두 줄이면 최소 수백 픽셀은 늘어난다. 잘려 나갔다면 늘어난 것이 거의 없다.
    check(f"{key} 결과물에 자막 글자가 실제로 새겨져 있다 (잘려 나가지 않았다)",
          gained > 300,
          f"자막 있음 {lit}개 - 자막 없음 {dark}개 = 글자 {gained}개")


# ══════════════════════════════════════════════════════════════
# 10. 나레이션을 입힌 영상에도 화면비가 적용되는가
#     이 경로는 소리를 섞는 필터를 함께 쓰기 때문에, 자막 영상과 코드가 다르다.
#     화면비를 바꾸지 않을 때는 화면을 그대로 복사해 빠르고, 바꿀 때만 다시 그린다.
# ══════════════════════════════════════════════════════════════
print("\n=== 10. 나레이션 영상에도 화면비가 적용되는가 (인터넷 필요) ===")
try:
    proj["script"] = "화면비 점검용 문장입니다. 두 번째 문장입니다."
    proj["output"] = {"aspect": "source", "fit": "crop", "focus_x": 50, "focus_y": 50,
                      "pad_blur": True}
    api(f"/api/projects/{pid}", "PUT", proj)

    job = api(f"/api/projects/{pid}/narration", "POST",
              {"script": proj["script"], "voice": "ko-KR-SunHiNeural"})
    run_job(job["job_id"], limit=300)

    # (1) 원본 그대로 — 화면을 손대지 않는다
    job = api(f"/api/projects/{pid}/narration/export", "POST",
              {"kind": "video", "original_volume": 30})
    plain = Path(run_job(job["job_id"], limit=300)["path"])
    check("원본 그대로일 때 나레이션 영상 크기가 원본과 같다",
          probe_size(plain) == (SRC_W, SRC_H), f"{probe_size(plain)}")

    # (2) 세로 9:16 — 실제로 잘려 나와야 한다
    fresh = api(f"/api/projects/{pid}")
    fresh["output"] = {"aspect": "9:16", "fit": "crop", "focus_x": 50, "focus_y": 50,
                       "pad_blur": True}
    api(f"/api/projects/{pid}", "PUT", fresh)

    job = api(f"/api/projects/{pid}/narration/export", "POST",
              {"kind": "video", "original_volume": 30})
    result = run_job(job["job_id"], limit=600)
    tall = Path(result["path"])
    want = api(f"/api/system/framing?w={SRC_W}&h={SRC_H}&aspect=9:16&fit=crop")
    check("나레이션 영상도 세로 9:16 로 잘려 나온다",
          probe_size(tall) == (want["width"], want["height"]),
          f"실제 {probe_size(tall)} / 기대 ({want['width']}, {want['height']})")
    check("나레이션 영상에도 소리가 들어 있다",
          bool(result.get("duration")), f"길이 {result.get('duration')}초")
except urllib.error.HTTPError as exc:
    check("나레이션 영상 화면비 점검", False, f"HTTP {exc.code}: {exc.read()[:200]!r}")
except Exception as exc:
    check("나레이션 영상 화면비 점검", False,
          f"{type(exc).__name__}: {exc} (인터넷이 끊겨 있으면 음성을 만들 수 없습니다)")


# ══════════════════════════════════════════════════════════════
# 11. 뒷정리
# ══════════════════════════════════════════════════════════════
print("\n=== 11. 뒷정리 ===")
try:
    api(f"/api/projects/{pid}", "DELETE")
    check("점검용 프로젝트를 지웠다", True)
except Exception as exc:
    check("점검용 프로젝트를 지웠다", False, str(exc))


# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 62)
print(f"  통과 {len(passed)}개 · 실패 {len(failed)}개")
if failed:
    print("\n  실패한 항목:")
    for name in failed:
        print(f"   - {name}")
print("=" * 62)
sys.exit(1 if failed else 0)
