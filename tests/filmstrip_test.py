"""영상 띠(필름스트립) 점검 — 타임라인에 깔 그림이 실제 장면과 맞는가.

사용법:
    1) 서버를 띄운다      python -m app --port 8766
    2) 이 파일을 실행한다  set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
                          python tests/filmstrip_test.py

    ※ 인터넷이 필요 없다. 시험 영상은 이 파일이 직접 만든다.

──────────────────────────────────────────────────────────────────────
어떻게 "맞다"를 판정하는가

시험 영상을 **1초마다 색이 완전히 바뀌게** 만든다 (빨강·초록·파랑 …).
그러면 띠의 어느 자리를 잘라 색을 재기만 해도 "그 자리가 몇 초를 담고 있는지"를
숫자로 확인할 수 있다.

이 검사가 필요한 이유는 이 프로젝트가 이미 한 번 데였기 때문이다 —
`fps` 필터가 앞부분을 통째로 잘라먹는데도 FFmpeg 은 오류 없이 끝났다
(memory/fps-filter-eats-the-first-images.md). 띠도 같은 필터를 쓰므로,
"그림이 나왔다"만 보면 **앞 장면이 밀린 띠**를 정상으로 착각하게 된다.
그래서 그림이 나왔는지가 아니라 **몇 초짜리 화면이 어느 자리에 있는지**를 잰다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
SAMPLE_DIR = ROOT / "tests" / "sample"
COLOR_VIDEO = SAMPLE_DIR / "sample_colors_20s.mp4"
WORK = Path(os.environ.get("TEMP", ".")) / "moviefit_filmstrip_check"

# 1초마다 이 색으로 바뀐다. 서로 충분히 멀어서 압축으로 흐려져도 구별된다.
COLORS = [
    ("red", (255, 0, 0)), ("lime", (0, 255, 0)), ("blue", (0, 0, 255)),
    ("yellow", (255, 255, 0)), ("magenta", (255, 0, 255)), ("cyan", (0, 255, 255)),
    ("white", (255, 255, 255)), ("black", (0, 0, 0)), ("orange", (255, 165, 0)),
    ("navy", (0, 0, 128)), ("olive", (128, 128, 0)), ("teal", (0, 128, 128)),
    ("purple", (128, 0, 128)), ("maroon", (128, 0, 0)), ("green", (0, 128, 0)),
    ("silver", (192, 192, 192)), ("gray", (128, 128, 128)), ("skyblue", (135, 206, 235)),
    ("brown", (165, 42, 42)), ("crimson", (220, 20, 60)),
]
# ※ 색은 서로 충분히 달라야 한다. 처음에는 aqua(=cyan) 와 fuchsia(=magenta) 를 넣었다가
#   "17초 화면이 5초로 나온다"는 엉뚱한 실패를 봤다. 같은 색이니 구별될 리가 없었다.
#   아래 [0] 에서 실제로 서로 다른지 검사해서 이 함정이 되풀이되지 않게 한다.

passed: list[str] = []
failed: list[str] = []
made: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    print(f"[{'  OK  ' if ok else ' FAIL '}] {name}" + (f"   — {detail}" if detail else ""))
    return bool(ok)


def req(path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(
        BASE + urllib.parse.quote(path, safe="/?&=.:%-"), data=data, method=method
    )
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=300) as res:
            raw = res.read().decode("utf-8")
            return res.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:300]}


def fetch_bytes(path: str) -> tuple[int, bytes, float]:
    """그림을 받아 (상태, 내용, 걸린초) 로 돌려준다."""
    url = BASE + urllib.parse.quote(path, safe="/?&=.:%-")
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=600) as res:
            return res.status, res.read(), time.time() - started
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), time.time() - started


def make_color_video() -> None:
    """1초마다 색이 바뀌는 20초짜리 영상을 만든다 (없을 때만)."""
    if COLOR_VIDEO.is_file():
        return
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  시험 영상을 만듭니다: {COLOR_VIDEO.name} (색이 1초마다 바뀝니다)")

    cmd = ["ffmpeg", "-y", "-v", "error"]
    for name, _rgb in COLORS:
        cmd += ["-f", "lavfi", "-t", "1", "-i", f"color=c={name}:s=320x180:r=15"]
    chain = "".join(f"[{i}:v]" for i in range(len(COLORS)))
    cmd += [
        "-filter_complex", f"{chain}concat=n={len(COLORS)}:v=1:a=0[v]",
        "-map", "[v]", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "18",
        str(COLOR_VIDEO),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or b"").decode("utf-8", "replace")[:400])


def image_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True,
    )
    w, h = out.stdout.strip().split("x")
    return int(w), int(h)


def region_color(path: Path, x: int, y: int, w: int, h: int) -> tuple[int, int, int]:
    """그림의 한 조각을 잘라 평균 색을 잰다 (1픽셀로 줄여서 읽는다)."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"crop={w}:{h}:{x}:{y},scale=1:1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    raw = out.stdout
    if len(raw) < 3:
        raise RuntimeError("색을 읽지 못했습니다: " + (out.stderr or b"").decode("utf-8", "replace")[:200])
    return raw[0], raw[1], raw[2]


def distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def nearest_color(rgb: tuple[int, int, int]) -> tuple[int, float]:
    """가장 가까운 시험 색이 몇 번째(=몇 초)인지와 그 거리."""
    best, best_d = -1, float("inf")
    for i, (_name, ref) in enumerate(COLORS):
        d = distance(rgb, ref)
        if d < best_d:
            best, best_d = i, d
    return best, best_d


def main() -> int:
    print("\n" + "=" * 70)
    print("  영상 띠(필름스트립) 점검 — 띠의 자리가 실제 시각과 맞는가")
    print("=" * 70)
    print(f"  서버: {BASE}")

    try:
        req("/api/health")
    except urllib.error.URLError:
        print("  서버에 연결할 수 없습니다. 'python -m app' 을 먼저 실행하세요.")
        return 1

    # ── 0. 시험 색이 서로 구별되는가 ─────────────────────
    # 이 검사가 없으면 "같은 색 두 개"를 넣어 놓고 제품이 틀렸다고 오해한다 (실제로 겪었다).
    print("\n[0] 시험용 색들이 서로 충분히 다른가")
    worst, pair = 1e9, ("", "")
    for i, (na, ra) in enumerate(COLORS):
        for nb, rb in COLORS[i + 1:]:
            d = distance(ra, rb)
            if d < worst:
                worst, pair = d, (na, nb)
    check("시험 색 20개가 서로 구별된다", worst >= 50,
          f"가장 가까운 짝 {pair[0]}↔{pair[1]} 거리 {worst:.0f} (50 이상이어야 함)")
    if worst < 50:
        return 1

    WORK.mkdir(parents=True, exist_ok=True)
    COLOR_VIDEO.unlink(missing_ok=True)  # 색 목록이 바뀌었을 수 있으므로 항상 새로 만든다
    try:
        make_color_video()
    except RuntimeError as exc:
        check("시험 영상 만들기", False, str(exc))
        return 1
    check("시험 영상 준비", COLOR_VIDEO.is_file(), COLOR_VIDEO.name)

    # ── 1. 띠를 만든다 ───────────────────────────────────
    print("\n[1] 영상 띠 만들기")
    status, proj = req("/api/projects", "POST",
                       {"name": "영상띠점검", "video_path": str(COLOR_VIDEO), "mode": "video"})
    if not check("프로젝트 생성", status == 201, f"HTTP {status}"):
        return 1
    pid = proj["id"]
    made.append(pid)

    status, body, first_sec = fetch_bytes(f"/media/project/{pid}/filmstrip")
    if not check("띠 그림을 받았다", status == 200 and len(body) > 1000,
                 f"HTTP {status} · {len(body) / 1024:.0f}KB · {first_sec:.1f}초"):
        return 1

    strip = WORK / "strip.jpg"
    strip.write_bytes(body)
    width, height = image_size(strip)
    print(f"      띠 크기: {width}×{height}px")
    check("띠는 가로로 긴 한 줄이다", width > height * 20, f"{width}×{height}")

    from app.core import filmstrip as fs

    expect_count = fs.frame_count_for(20.0)
    check("칸 수가 영상 길이에 맞게 정해졌다", expect_count == fs.MIN_FRAMES,
          f"20초 영상 → {expect_count}칸 (최소 {fs.MIN_FRAMES}칸)")
    check("띠 높이가 정해진 값과 같다", height == fs.FRAME_HEIGHT,
          f"{height}px (기대 {fs.FRAME_HEIGHT}px)")

    # ── 2. 자리와 시각이 맞는가 (핵심) ───────────────────
    print("\n[2] 판정 — 띠의 자리가 실제 시각과 맞는가")
    print("      (색이 1초마다 바뀌므로, 자리의 색을 재면 몇 초인지 알 수 있다)")

    duration = 20.0
    mismatches = []
    for second in range(len(COLORS)):
        # 그 초의 한가운데를 겨냥한다 (경계에 걸리면 두 색이 섞인다)
        t = second + 0.5
        x = int(width * t / duration)
        x = max(0, min(width - 4, x))
        rgb = region_color(strip, x, 0, 3, height)
        guess, dist = nearest_color(rgb)
        ok = guess == second
        if not ok:
            mismatches.append((second, guess, dist))
        mark = " " if ok else "←틀림"
        print(f"      {second:>2}초 ({COLORS[second][0]:>8}) → 잰 색 {str(rgb):<18} "
              f"가장 가까운 색 = {guess:>2}초 {mark}")

    check(
        "모든 시각의 화면이 띠의 제자리에 있다 (앞이 밀리거나 잘리지 않았다)",
        not mismatches,
        "어긋난 곳: " + ", ".join(f"{s}초→{g}초" for s, g, _ in mismatches) if mismatches else "20곳 모두 일치",
    )

    # 첫 칸이 정말 영상의 시작인가 — fps 필터가 앞을 먹는 사고를 겨냥한 검사
    first_rgb = region_color(strip, 1, 0, 3, height)
    first_guess, _ = nearest_color(first_rgb)
    check("띠의 맨 앞이 영상의 0초다", first_guess == 0,
          f"맨 앞 색 = {first_guess}초 ({COLORS[first_guess][0]})")

    # ── 3. 캐시 ──────────────────────────────────────────
    print("\n[3] 두 번째부터는 즉시 나오는가 (캐시)")
    status2, body2, second_sec = fetch_bytes(f"/media/project/{pid}/filmstrip")
    check("두 번째 요청도 성공", status2 == 200, f"HTTP {status2}")
    check("내용이 같다", body2 == body, f"{len(body2) / 1024:.0f}KB")
    check("두 번째는 눈에 띄게 빠르다 (다시 만들지 않는다)",
          second_sec < max(0.5, first_sec * 0.5),
          f"처음 {first_sec:.2f}초 → 두 번째 {second_sec:.2f}초")

    # ── 4. 잘못된 경우 ───────────────────────────────────
    print("\n[4] 잘못된 경우에도 한국어로 답하는가")
    status, body3 = req("/media/project/없는프로젝트/filmstrip")
    detail = str(body3.get("detail", ""))
    check("없는 프로젝트 → 404 + 한국어", status == 404 and detail[:1] >= "가",
          f"HTTP {status} · {detail[:50]}")

    status, empty = req("/api/projects", "POST", {"name": "영상띠_대본", "mode": "script"})
    if status == 201:
        made.append(empty["id"])
        status, body4 = req(f"/media/project/{empty['id']}/filmstrip")
        detail = str(body4.get("detail", ""))
        check("영상 없는 프로젝트 → 404 + 한국어", status == 404 and detail[:1] >= "가",
              f"HTTP {status} · {detail[:50]}")

    return 0


def cleanup() -> None:
    for pid in made:
        try:
            req(f"/api/projects/{pid}", "DELETE")
        except Exception:
            pass


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    finally:
        cleanup()
        print("\n" + "=" * 70)
        print(f"  통과 {len(passed)}개 · 실패 {len(failed)}개")
        if failed:
            print("\n  실패한 항목:")
            for name in failed:
                print(f"    - {name}")
        print("=" * 70 + "\n")
    sys.exit(1 if failed else code)
