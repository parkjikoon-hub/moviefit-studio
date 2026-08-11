"""동작 점검(스모크 테스트) — 서버가 켜진 상태에서 핵심 기능이 실제로 도는지 확인한다.

사용법:
    1) 다른 창에서 서버를 켠다:  python -m app
    2) python tests/smoke_test.py

각 Phase의 수용 기준을 여기에 계속 추가한다.
"""

from __future__ import annotations

import email.message
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8765"
SAMPLE_VIDEO = ROOT / "tests" / "sample" / "sample_10s.mp4"

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

    # 서버를 껐다 켜도 남는지는 파일이 실제로 있는지로 확인한다
    json_path = ROOT / "projects" / project_id / "project.json"
    check("디스크에 project.json 존재", json_path.is_file(), str(json_path))

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

    # ── 뒷정리 ──────────────────────────────────────────
    print("\n[6] 뒷정리")
    status, _, _ = request(f"/api/projects/{project_id}", "DELETE")
    check("테스트 프로젝트 삭제", status == 204, f"HTTP {status}")

    print("\n" + "=" * 66)
    print(f"  통과 {passed}개 · 실패 {failed}개")
    print("=" * 66 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
