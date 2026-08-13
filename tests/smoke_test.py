"""동작 점검(스모크 테스트) — 서버가 켜진 상태에서 핵심 기능이 실제로 도는지 확인한다.

사용법:
    1) 다른 창에서 서버를 켠다:  python -m app
    2) python tests/smoke_test.py

각 Phase의 수용 기준을 여기에 계속 추가한다.
"""

from __future__ import annotations

import email.message
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 설치본이 8765를 쓰고 있으면 개발 서버를 다른 포트로 띄우고 여기로 겨냥한다.
#   예)  set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")
SAMPLE_VIDEO = ROOT / "tests" / "sample" / "sample_10s.mp4"

# 프로젝트가 저장될 수 있는 곳. 개발 서버는 앞쪽, 설치본은 뒤쪽에 저장한다.
PROJECT_ROOTS = [
    ROOT / "projects",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MovieFit Studio" / "projects",
]


def find_project_json(project_id: str) -> Path | None:
    """프로젝트 저장 파일을 두 곳에서 찾는다. 없으면 None."""
    for root in PROJECT_ROOTS:
        candidate = root / project_id / "project.json"
        if candidate.is_file():
            return candidate
    return None

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [통과] {label}" + (f"  ({detail})" if detail else ""))
    else:
        failed += 1
        print(f"  [실패] {label}" + (f"  ({detail})" if detail else ""))
    return condition


def request(
    path: str, method: str = "GET", body: dict | None = None, headers: dict | None = None
) -> tuple[int, "email.message.Message", bytes]:
    """서버에 요청을 보내고 (상태코드, 응답헤더, 본문)을 돌려준다.

    주소에 한글이 들어가면 그대로는 보낼 수 없으므로 %표기로 바꿔서 보낸다
    (브라우저는 encodeURIComponent로 같은 일을 자동으로 한다).
    """
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    safe_path = urllib.parse.quote(path, safe="/?&=.")
    req = urllib.request.Request(BASE + safe_path, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    # res.headers를 그대로 돌려준다. 이 객체는 대소문자를 구분하지 않고 조회되는데,
    # 서버(uvicorn)는 헤더 이름을 전부 소문자로 보내므로 dict로 바꾸면 조회에 실패한다.
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, res.headers, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def as_json(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))


def main() -> int:
    print("\n" + "=" * 66)
    print("  MovieFit Studio 동작 점검")
    print("=" * 66)

    # ── 서버 연결 ────────────────────────────────────────
    print("\n[1] 서버 연결")
    try:
        status, _, raw = request("/api/health")
    except urllib.error.URLError as exc:
        print(f"  [실패] 서버에 연결할 수 없습니다: {exc}")
        print("        다른 창에서 'python -m app' 을 먼저 실행하세요.")
        return 1
    check("health 응답", status == 200 and as_json(raw).get("ok") is True)

    # ── 프로젝트 만들기 (한글 이름) ──────────────────────
    print("\n[2] 프로젝트 만들기와 저장 (F-02)")
    korean_name = "검증용_한글이름_테스트"
    status, _, raw = request(
        "/api/projects",
        "POST",
        {"name": korean_name, "video_path": str(SAMPLE_VIDEO), "mode": "video"},
    )
    ok = check("영상 프로젝트 생성", status == 201, f"HTTP {status}")
    if not ok:
        print(f"        응답: {raw[:300]!r}")
        return 1

    created = as_json(raw)
    project_id = created["id"]
    check("한글 프로젝트 이름 보존", created["name"] == korean_name, created["name"])
    check("폴더 이름에 한글 유지", korean_name.replace(" ", "_") in project_id, project_id)
    check("영상 경로 등록", created["video_path"] == str(SAMPLE_VIDEO))
    check("기본 스타일 포함", created["style"]["color"] == "#FFFFFF")

    # ── 수정 후 저장 → 다시 읽기 ─────────────────────────
    created["segments"] = [
        {"id": "s001", "start": 0.5, "end": 2.0, "text": "첫 번째 자막입니다."},
        {"id": "s002", "start": 2.3, "end": 4.1, "text": "두 번째 자막입니다."},
    ]
    created["style"]["size"] = 55
    status, _, raw = request(f"/api/projects/{project_id}", "PUT", created)
    check("프로젝트 저장(PUT)", status == 200, f"HTTP {status}")

    status, _, raw = request(f"/api/projects/{project_id}")
    reloaded = as_json(raw)
    check("저장 내용 유지 — 자막 2개", len(reloaded["segments"]) == 2)
    check("저장 내용 유지 — 한글 자막", reloaded["segments"][0]["text"] == "첫 번째 자막입니다.")
    check("저장 내용 유지 — 스타일", reloaded["style"]["size"] == 55)

    # 서버를 껐다 켜도 남는지는 파일이 실제로 있는지로 확인한다.
    # 이 점검을 설치본(바탕화면 아이콘으로 띄운 것)에 대고 돌릴 수도 있는데,
    # 설치본은 자기 설치 폴더에 저장하므로 개발 폴더만 보면 "없다"고 잘못 판정한다.
    # 그래서 두 곳을 모두 살핀다.
    json_path = find_project_json(project_id)
    check("디스크에 project.json 존재", json_path is not None,
          str(json_path) if json_path else f"{' 와 '.join(str(r) for r in PROJECT_ROOTS)} 어디에도 없음")

    status, _, raw = request("/api/projects")
    ids = [p["id"] for p in as_json(raw)["projects"]]
    check("최근 프로젝트 목록에 포함", project_id in ids, f"{len(ids)}개")

    # ── 영상 스트리밍 (Range) ────────────────────────────
    print("\n[3] 영상 재생·탐색 (Range 요청)")
    status, headers, raw = request(f"/media/project/{project_id}/video")
    check("전체 요청 200", status == 200, f"{len(raw)} bytes")
    check("Accept-Ranges 헤더", headers.get("Accept-Ranges") == "bytes")
    full_size = len(raw)

    status, headers, raw = request(
        f"/media/project/{project_id}/video", headers={"Range": "bytes=100-199"}
    )
    check("부분 요청 206", status == 206, f"HTTP {status}")
    check("정확히 100바이트 수신", len(raw) == 100, f"{len(raw)} bytes")
    check(
        "Content-Range 헤더",
        headers.get("Content-Range") == f"bytes 100-199/{full_size}",
        headers.get("Content-Range", "없음"),
    )

    # ── 잘못된 입력 처리 (N-05) ─────────────────────────
    print("\n[4] 잘못된 입력을 넣어도 죽지 않는가")
    status, _, raw = request(
        "/api/projects", "POST", {"name": "없는파일", "video_path": "C:/없는폴더/없다.mp4"}
    )
    check("없는 파일 → 400과 한국어 안내", status == 400 and "찾을 수 없습니다" in as_json(raw)["detail"])

    status, _, raw = request(
        "/api/projects", "POST", {"name": "잘못된형식", "video_path": str(ROOT / "README.md")}
    )
    check("지원 안 하는 확장자 → 400", status == 400 and "지원하지 않는" in as_json(raw)["detail"])

    status, _, raw = request("/api/projects/이런건없다")
    check("없는 프로젝트 → 404", status == 404)

    status, _, raw = request(f"/media/project/{project_id}/file/../../secret.txt")
    check("프로젝트 폴더 밖 접근 차단", status in (403, 404), f"HTTP {status}")

    # ── 화면 파일과 PWA ─────────────────────────────────
    print("\n[5] 화면 파일과 PWA 아이콘")
    for path, label in [
        ("/", "시작 화면(index.html)"),
        ("/style.css", "스타일시트"),
        ("/app.js", "화면 동작 코드"),
        ("/manifest.webmanifest", "PWA 설치 정보"),
        ("/sw.js", "서비스 워커"),
        ("/icons/icon-192.png", "아이콘 192"),
        ("/icons/icon-512.png", "아이콘 512"),
        ("/icons/maskable-512.png", "마스커블 아이콘"),
        ("/favicon.ico", "파비콘"),
    ]:
        status, _, raw = request(path)
        check(label, status == 200 and len(raw) > 0, f"{len(raw)} bytes")

    status, _, raw = request("/manifest.webmanifest")
    manifest = as_json(raw)
    check("manifest에 아이콘 4종", len(manifest["icons"]) == 4)
    check("manifest 설치 모드", manifest["display"] == "standalone")

    # ── 스타일·글꼴·목소리 ──────────────────────────────
    print("\n[6] 자막 스타일과 목소리")
    status, _, raw = request("/api/styles/presets")
    data = as_json(raw)
    check("프리셋 5종", status == 200 and len(data["builtin"]) == 5, f"{len(data['builtin'])}개")
    check("프리셋에 자유 위치 항목", "position" in data["builtin"][0]["style"])

    status, _, raw = request("/api/styles/fonts")
    fonts = as_json(raw)["fonts"]
    check("글꼴 목록", status == 200 and len(fonts) > 0, f"{len(fonts)}개")
    check("번들 폰트 포함", any(f["bundled"] for f in fonts))

    status, _, raw = request("/api/tts/voices?korean_only=true")
    voices = as_json(raw)
    check("한국어 가능 목소리", status == 200 and voices["korean_capable_count"] >= 3,
          f"전용 {voices['korean_native_count']}개 / 가능 {voices['korean_capable_count']}개")

    # ── 소리 분석 (파형·무음) ───────────────────────────
    print("\n[7] 소리 분석 — 타이밍 보조 기능")
    status, _, raw = request(f"/api/audio/waveform/{project_id}?buckets=500")
    if check("파형 데이터", status == 200, f"HTTP {status}"):
        wave = as_json(raw)
        check("요청한 개수만큼 반환", len(wave["peaks"]) == 500, f"{len(wave['peaks'])}개")
        check("값이 0~1 범위", all(0.0 <= p <= 1.0 for p in wave["peaks"]))
        check("소리가 실제로 감지됨", max(wave["peaks"]) > 0.1, f"최대 {max(wave['peaks']):.3f}")

    status, _, raw = request(f"/api/audio/silence/{project_id}")
    if check("무음 감지", status == 200, f"HTTP {status}"):
        regions = as_json(raw)["regions"]
        check("말소리 구간 검출", len(regions) >= 1, f"{len(regions)}개 구간")

    # ── 자동 백업 ───────────────────────────────────────
    print("\n[8] 자동 백업 — 실수해도 되돌릴 수 있는가")
    reloaded["segments"] = []  # 실수로 전부 지운 상황을 흉내 낸다
    request(f"/api/projects/{project_id}", "PUT", reloaded)

    status, _, raw = request(f"/api/projects/{project_id}/backups")
    backups = as_json(raw)["backups"]
    if check("백업 목록 조회", status == 200 and len(backups) >= 1, f"{len(backups)}개"):
        newest = backups[0]["file"]
        status, _, raw = request(f"/api/projects/{project_id}/backups/{newest}/restore", "POST")
        restored = as_json(raw)
        check("백업에서 되돌리기", status == 200 and len(restored["segments"]) == 2,
              f"자막 {len(restored['segments'])}개 복구")

    # ── 뒷정리 ──────────────────────────────────────────
    print("\n[9] 뒷정리")
    status, _, _ = request(f"/api/projects/{project_id}", "DELETE")
    check("테스트 프로젝트 삭제", status == 204, f"HTTP {status}")

    print("\n" + "=" * 66)
    print(f"  통과 {passed}개 · 실패 {failed}개")
    print("=" * 66 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
