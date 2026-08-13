"""Phase 6 점검 — 사진 영상 · 음원 영상 · 자막 강제정렬.

사용법:
    1) 개발 서버를 띄운다      python -m app --port 8766
    2) 시험용 사진을 만든다    python tools/make_sample_images.py --count 30
    3) 이 파일을 실행한다      set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
                              python tests/phase6_test.py

이 점검이 특히 겨냥하는 것 — **오류 없이 틀린 결과**:
  · 크기가 다른 사진을 이어붙일 때 FFmpeg 은 종료 코드 0으로 끝나면서
    "마지막 사진만 되풀이되는 영상"을 내놓는다 (RESEARCH 2.1절 실측).
    그래서 만든 영상의 **특정 시각 화면 색**을 재어 몇 번째 사진인지 맞대 본다.
    이 검사를 빼면 사진 3장으로는 언제나 통과하고 사용자가 30장 넣을 때 터진다.
  · 미리보기의 자막 자리와 실제로 새겨지는 자리가 어긋나는 결함
    (memory/preview-must-use-the-output-frame.md) 이 사진 프로젝트에서 되살아난다.
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

BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
IMAGES_DIR = ROOT / "tests" / "sample" / "images"
PROJECTS_DIR = ROOT / "projects"

passed: list[str] = []
failed: list[str] = []
made_projects: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    mark = "  OK  " if ok else " FAIL "
    print(f"[{mark}] {name}" + (f"   — {detail}" if detail else ""))
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


def api_error(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, str]:
    """실패를 기대하는 호출. (HTTP 상태, 오류 문구)를 돌려준다."""
    try:
        api(path, method, body)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw).get("detail", raw)
        except json.JSONDecodeError:
            return exc.code, raw
    return 0, ""


def sample_images(count: int) -> list[Path]:
    files = sorted(IMAGES_DIR.glob("*"))
    return files[:count]


def probe_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    stream = json.loads(out.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def frame_color(path: Path, at: float) -> tuple[int, int, int]:
    """영상의 특정 시각에서 화면 한가운데 색을 잰다.

    이 검사가 이 파일의 심장이다. 크기가 다른 사진을 잘못 이어붙이면 FFmpeg 이
    아무 오류 없이 "마지막 사진만 되풀이되는 영상"을 내놓는다. 길이만 재면
    통과하고, 색을 재야 드러난다.
    """
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=120,
    )
    raw = out.stdout
    if len(raw) < 3:
        raise RuntimeError(f"{at}초 지점의 화면을 읽지 못했습니다.")
    return (raw[0], raw[1], raw[2])


def image_color(path: Path) -> tuple[int, int, int]:
    """사진 한 장의 색 (한 가지 색으로 꽉 찬 시험용 사진이다)."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=120,
    )
    raw = out.stdout
    return (raw[0], raw[1], raw[2])


def close_color(a: tuple[int, int, int], b: tuple[int, int, int], tol: int = 14) -> bool:
    """jpeg 압축과 색 공간 변환 때문에 값이 조금 흔들린다. 그만큼은 봐준다."""
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def run_job(job_id: str, limit: float = 900.0) -> dict:
    deadline = time.time() + limit
    while time.time() < deadline:
        info = api(f"/api/jobs/{job_id}")
        if info["status"] == "done":
            return info.get("result") or {}
        if info["status"] in ("error", "cancelled"):
            raise RuntimeError(info.get("message") or info["status"])
        time.sleep(0.7)
    raise TimeoutError("작업이 제한 시간 안에 끝나지 않았습니다.")


def watch_job(job_id: str, limit: float = 900.0) -> tuple[dict, list[tuple[float, str]]]:
    """작업을 지켜보며 진행률과 문구를 모두 모아 둔다 (진행률이 진짜인지 보려고)."""
    seen: list[tuple[float, str]] = []
    deadline = time.time() + limit
    while time.time() < deadline:
        info = api(f"/api/jobs/{job_id}")
        seen.append((float(info.get("progress") or 0.0), str(info.get("message") or "")))
        if info["status"] == "done":
            return info.get("result") or {}, seen
        if info["status"] in ("error", "cancelled"):
            raise RuntimeError(info.get("message") or info["status"])
        time.sleep(0.4)
    raise TimeoutError("작업이 제한 시간 안에 끝나지 않았습니다.")


def cleanup() -> None:
    for pid in made_projects:
        try:
            api(f"/api/projects/{pid}", "DELETE")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
# 0. 준비 확인 — 겨냥한 서버가 정말 새 코드인가
# ══════════════════════════════════════════════════════════════
print("\n=== 0. 준비 ===")
try:
    health = api("/api/health")
    check("서버가 응답한다", bool(health.get("ok")), f"버전 {health.get('version')}")
except Exception as exc:  # noqa: BLE001
    print(f"\n서버에 닿지 못했습니다: {exc}\n  {BASE} 가 맞는지 확인해 주세요.")
    raise SystemExit(1)

# 버전 번호만으로는 부족하다. 이번에 새로 넣은 문자열이 화면에 있는지 본다.
# (memory/test-must-target-the-right-server.md)
with urllib.request.urlopen(BASE + "/", timeout=20) as _res:
    index_live = _res.read().decode("utf-8", "replace")
if not check(
    "겨냥한 서버가 Phase 6 코드를 서비스한다",
    'id="card-images"' in index_live,
    "시작 화면에 [사진으로 시작] 카드가 있다",
):
    print("\n옛 서버를 겨냥하고 있습니다. MOVIEFIT_TEST_URL 을 확인해 주세요.")
    raise SystemExit(1)

check(
    f"시험용 사진이 준비되어 있다 ({len(sample_images(999))}장)",
    len(sample_images(999)) >= 30,
    "부족하면 python tools/make_sample_images.py --count 30",
)


# ══════════════════════════════════════════════════════════════
# 1. 단계 1 — 사진이 들어올 통로
# ══════════════════════════════════════════════════════════════
print("\n=== 단계 1 · 사진이 들어올 통로 ===")

# 1-1. 파일 선택 창이 사진을 보여 주고 여러 장을 고를 수 있는가.
#      창을 사람이 눌러야 하므로, 창을 만드는 코드를 직접 읽어 확인한다.
#      (창이 실제로 뜨는 모습은 tests/phase6_dialog_check.py 에서 그림으로 확인한다)
dialog_src = (ROOT / "app" / "core" / "filedialog.py").read_text(encoding="utf-8")
check(
    "파일 선택 창의 사진 목록에 jpg·png·webp 가 모두 들어 있다",
    all(ext in dialog_src for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp")),
)
check(
    "사진은 여러 장을 한 번에 고르게 되어 있다 (askopenfilenames)",
    "askopenfilenames" in dialog_src,
    "끝에 s 가 붙은 함수라야 여러 장이 된다",
)

# 1-2. 사진 3장으로 프로젝트를 만들면 순서대로 들어가는가.
three = sample_images(3)
created = api(
    "/api/projects",
    "POST",
    {"name": "점검_사진3장", "image_paths": [str(p) for p in three], "mode": "video"},
)
made_projects.append(created["id"])

check("사진 3장으로 프로젝트가 만들어진다", len(created.get("images") or []) == 3,
      f"images {len(created.get('images') or [])}개")

saved = json.loads((PROJECTS_DIR / created["id"] / "project.json").read_text(encoding="utf-8"))
saved_paths = [img["path"] for img in saved.get("images", [])]
check(
    "project.json 의 images 에 경로 3개가 고른 순서 그대로 들어 있다",
    saved_paths == [str(p) for p in three],
    " / ".join(Path(p).name for p in saved_paths),
)
check(
    "사진마다 표시 시간이 정해져 있다",
    all(float(img.get("duration", 0)) > 0 for img in saved.get("images", [])),
    f"기본 {saved['images'][0]['duration']}초",
)
check(
    "사진 프로젝트는 화면 크기(캔버스)가 정해진다",
    (saved.get("canvas") or {}).get("width", 0) > 0,
    f"{(saved.get('canvas') or {}).get('width')}x{(saved.get('canvas') or {}).get('height')}",
)

# 1-3. 사진이 아닌 파일을 사진 자리에 넣으면 한국어로 거절하는가 (시스템 경계 검증).
code, detail = api_error(
    "/api/projects", "POST",
    {"name": "점검_잘못된사진", "image_paths": [str(ROOT / "README.md")]},
)
check(
    "사진이 아닌 파일을 사진 자리에 넣으면 한국어로 거절한다",
    code == 400 and "사진" in detail,
    detail[:60],
)

# 1-4. 옛 프로젝트가 지금과 똑같이 열리는가 (되돌아가기 확인).
#      images·canvas·audio_path 가 아예 없는 project.json 을 직접 만들어 읽혀 본다.
old_id = "00000000_000000_점검_옛프로젝트"
old_dir = PROJECTS_DIR / old_id
old_dir.mkdir(parents=True, exist_ok=True)
(old_dir / "project.json").write_text(
    json.dumps(
        {
            "version": 1, "id": old_id, "name": "점검_옛프로젝트",
            "video_path": None, "mode": "script", "script": "옛 대본",
            "segments": [{"id": "s1", "start": 0.0, "end": 2.0, "text": "옛 자막"}],
            "style": {}, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
made_projects.append(old_id)
try:
    old_loaded = api(f"/api/projects/{old_id}")
    check(
        "사진 항목이 아예 없는 옛 프로젝트가 그대로 열린다",
        old_loaded.get("name") == "점검_옛프로젝트" and len(old_loaded.get("segments", [])) == 1,
        "자막 1개 · 대본 유지",
    )
except Exception as exc:  # noqa: BLE001
    check("사진 항목이 아예 없는 옛 프로젝트가 그대로 열린다", False, str(exc)[:60])

listed = api("/api/projects")["projects"]
old_row = next((p for p in listed if p["id"] == old_id), None)
check(
    "옛 프로젝트가 최근 목록에도 정상으로 나온다",
    old_row is not None and old_row.get("image_count") == 0,
    "사진 0장으로 표시",
)
new_row = next((p for p in listed if p["id"] == created["id"]), None)
check(
    "사진 프로젝트는 최근 목록에 사진 장수가 나온다",
    new_row is not None and new_row.get("image_count") == 3,
    f"image_count={new_row.get('image_count') if new_row else '없음'}",
)


# ══════════════════════════════════════════════════════════════
# 2. 단계 2 — 사진을 영상으로 만든다 (자막 없이)
# ══════════════════════════════════════════════════════════════
print("\n=== 단계 2 · 사진을 영상으로 만든다 ===")

THIRTY = sample_images(30)
big = api(
    "/api/projects", "POST",
    {"name": "점검_사진30장", "image_paths": [str(p) for p in THIRTY], "mode": "video"},
)
made_projects.append(big["id"])

# 장당 3초, 세로 9:16 로 맞춘다. 사진 크기가 제각각이므로 잘라내기로 채운다.
big["output"] = {"aspect": "9:16", "fit": "crop", "focus_x": 50.0, "focus_y": 50.0, "pad_blur": True}
for img in big["images"]:
    img["duration"] = 3.0
api(f"/api/projects/{big['id']}", "PUT", big)

started = time.time()
job = api(f"/api/projects/{big['id']}/render", "POST", {"kind": "slideshow"})
result, timeline = watch_job(job["job_id"])
elapsed = time.time() - started
video = Path(result["path"])

check("사진 30장으로 영상이 만들어졌다", video.is_file(), f"{video.name} · {elapsed:.1f}초 걸림")

duration = probe_duration(video)
check(
    "길이가 90.0초 ± 0.1초 이다 (30장 × 3초)",
    abs(duration - 90.0) <= 0.1,
    f"실제 {duration:.3f}초",
)

width, height = probe_size(video)
check("크기가 정확히 1080×1920 이다", (width, height) == (1080, 1920), f"실제 {width}×{height}")

# ── 조용한 실패를 잡는 검사 (빼면 안 된다) ──────────────────
# 크기가 다른 사진을 잘못 이어붙이면 오류 없이 마지막 사진만 되풀이된다.
for at, nth in ((1.0, 1), (46.0, 16), (89.0, 30)):
    want = image_color(THIRTY[nth - 1])
    got = frame_color(video, at)
    check(
        f"t={at:.0f}초 화면이 {nth}번째 사진과 같다",
        close_color(got, want),
        f"기대 RGB{want} / 실제 RGB{got}",
    )

# ── 진행률이 진짜인가 ────────────────────────────────────────
progresses = [p for p, _ in timeline]
rising = sum(1 for a, b in zip(progresses, progresses[1:]) if b > a)
check(
    "진행률이 여러 번에 걸쳐 올라간다",
    rising >= 3 and max(progresses) >= 0.99,
    f"{len(progresses)}번 살펴 {rising}번 올랐다 (최대 {max(progresses):.2f})",
)
# 문구에 실제 영상 시각이 들어 있으면 FFmpeg 이 보고한 진짜 진척이다 (타이머 흉내가 아니다).
times: list[int] = []
for _p, message in timeline:
    m = re.search(r"\((?:(\d+)분\s*)?(\d+)초 / ", message)
    if m:
        times.append(int(m.group(1) or 0) * 60 + int(m.group(2)))
check(
    "진행률이 FFmpeg 이 실제로 처리한 시각을 따라간다 (타이머 흉내가 아니다)",
    len(times) >= 2 and times == sorted(times) and times[-1] > times[0],
    f"보고된 처리 시각: {times[:3]} … {times[-1]}초" if times else "시각이 든 문구가 없었다",
)
# 사진 준비 단계도 진행률에 보여야 한다 (30장이면 눈에 띄게 걸린다).
check(
    "사진을 준비하는 동안에도 무엇을 하는지 알려 준다",
    any("사진을 준비하고" in message for _p, message in timeline),
    "'사진을 준비하고 있습니다 (n / 30장)' 문구",
)

# ── 취소하면 정말 멈추고 반쪽 파일이 안 남는가 ───────────────
out_dir = PROJECTS_DIR / big["id"] / "out"
before = {p.name for p in out_dir.glob("*")}
job2 = api(f"/api/projects/{big['id']}/render", "POST", {"kind": "slideshow"})
time.sleep(2.5)
api(f"/api/jobs/{job2['job_id']}/cancel", "POST")
cancelled = False
for _ in range(40):
    info = api(f"/api/jobs/{job2['job_id']}")
    if info["status"] in ("cancelled", "error", "done"):
        cancelled = info["status"] == "cancelled"
        break
    time.sleep(0.5)
check("만드는 도중 [취소]를 누르면 실제로 멈춘다", cancelled, f"상태 {info['status']}")

leftovers = [p.name for p in out_dir.glob("*") if p.name not in before and p.suffix == ".mp4"]
half_files = [p.name for p in out_dir.glob(".*")]
check(
    "취소한 뒤 반쪽짜리 파일이 남지 않는다",
    not leftovers and not half_files,
    f"새로 생긴 것: {leftovers + half_files}" if (leftovers or half_files) else "깨끗함",
)

# ── 두 번째 내보내기는 준비를 다시 하지 않는다 (정규화 캐시) ──
cache_files = list((PROJECTS_DIR / big["id"] / "cache").glob("norm_*.jpg"))
check(
    "정규화한 사진이 프로젝트 폴더에 남아 다음번에 다시 쓰인다",
    len(cache_files) == 30,
    f"cache/ 에 {len(cache_files)}장",
)


# ══════════════════════════════════════════════════════════════
# 3. 단계 4 — 사진 영상에 자막을 얹는다
# ══════════════════════════════════════════════════════════════
print("\n=== 단계 4 · 사진 영상에 자막을 얹는다 ===")

# 프로젝트 이름에 FFmpeg 필터 문법의 구분자를 일부러 넣는다.
# 이 문자들이 걸러지지 않으면 렌더링이 통째로 실패하는데 오류 메시지로는 원인을
# 절대 못 찾는다 (memory/ffmpeg-filter-path-escaping.md 회귀 검사).
TRICKY = "사진, 시험;[a]'b"
tricky = api(
    "/api/projects", "POST",
    {"name": TRICKY, "image_paths": [str(p) for p in sample_images(3)], "mode": "video"},
)
made_projects.append(tricky["id"])
tricky["output"] = {"aspect": "9:16", "fit": "crop", "focus_x": 50.0, "focus_y": 50.0,
                    "pad_blur": True}
tricky["segments"] = [{"id": "s1", "start": 0.2, "end": 6.0, "text": "한글 자막 시험"}]
api(f"/api/projects/{tricky['id']}", "PUT", tricky)

burned = run_job(api(f"/api/projects/{tricky['id']}/render", "POST", {"kind": "burn"})["job_id"])
burned_path = Path(burned["path"])
check(
    f"프로젝트 이름을 「{TRICKY}」 로 지어도 자막 영상이 만들어진다",
    burned_path.is_file(),
    burned_path.name,
)
check(
    "사진 프로젝트의 자막 영상도 캔버스 크기(1080×1920)로 나온다",
    probe_size(burned_path) == (1080, 1920),
    f"{probe_size(burned_path)}",
)


# ── 한글이 네모(□)로 나오지 않는가 ─────────────────────────────
#
# 글꼴을 못 찾으면 libass 는 모든 글자를 **똑같은 네모 하나**로 그린다.
# 그래서 "글자 픽셀이 있는가"만 보면 통과한다. 대신 **서로 다른 한글 두 벌**을
# 그려서 그림이 실제로 다른지 본다. 네모라면 두 그림이 거의 같을 것이다.
def ink_mask(project_id: str, text: str) -> tuple[bytes, Path]:
    data = api(f"/api/projects/{project_id}")
    data["segments"] = [dict(data["segments"][0], text=text)]
    api(f"/api/projects/{project_id}", "PUT", data)
    out = run_job(
        api(f"/api/projects/{project_id}/render", "POST",
            {"kind": "preview", "preview_seconds": 3})["job_id"]
    )
    path = Path(out["path"])
    frame = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", "1.0", "-i", str(path), "-frames:v", "1",
         "-vf", "scale=270:480", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, timeout=180,
    ).stdout
    return frame, path


blank_frame, _ = ink_mask(tricky["id"], "")
frame_a, _ = ink_mask(tricky["id"], "국물떡볶이")
frame_b, _ = ink_mask(tricky["id"], "가나다라마")

if min(len(blank_frame), len(frame_a), len(frame_b)) < 270 * 480:
    check("한글 자막이 네모(□)가 아니다", False, "프레임을 읽지 못했다")
else:
    mask_a = [1 if abs(frame_a[i] - blank_frame[i]) > 24 else 0 for i in range(270 * 480)]
    mask_b = [1 if abs(frame_b[i] - blank_frame[i]) > 24 else 0 for i in range(270 * 480)]
    ink_a, ink_b = sum(mask_a), sum(mask_b)
    differ = sum(1 for i in range(270 * 480) if mask_a[i] != mask_b[i])
    check("자막 글자가 실제로 새겨졌다", ink_a > 200 and ink_b > 200, f"글자 픽셀 {ink_a} / {ink_b}")
    check(
        "한글이 네모(□)가 아니다 (서로 다른 글자가 서로 다르게 그려진다)",
        ink_a > 0 and differ / max(1, min(ink_a, ink_b)) > 0.25,
        f"두 글자열의 그림이 {differ}픽셀 다르다 (글자 픽셀 {min(ink_a, ink_b)}개 대비)",
    )


# ══════════════════════════════════════════════════════════════
# 마무리
# ══════════════════════════════════════════════════════════════
cleanup()

print("\n" + "=" * 66)
print(f"  통과 {len(passed)}개 · 실패 {len(failed)}개")
print("=" * 66)
if failed:
    for name in failed:
        print(f"  실패: {name}")
raise SystemExit(1 if failed else 0)
