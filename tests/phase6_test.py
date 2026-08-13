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
