"""FastAPI 앱 정의 — 라우트를 모으고 화면 파일(static)을 서빙한다."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import media as media_api
from app.api import projects as projects_api
from app.api import styles as styles_api
from app.api import system as system_api
from app.api import tts as tts_api
from app.config import STATIC_DIR, ensure_dirs

log = logging.getLogger("moviefit_studio")


def create_app() -> FastAPI:
    ensure_dirs()

    app = FastAPI(title="MovieFit Studio", version=__version__, docs_url="/api/docs")

    app.include_router(projects_api.router)
    app.include_router(media_api.router)
    app.include_router(system_api.router)
    app.include_router(styles_api.router)
    app.include_router(tts_api.router)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """예상 못 한 오류도 프로그램을 죽이지 않고 한국어로 알려준다 (N-05)."""
        log.exception("처리되지 않은 오류: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "예상하지 못한 오류가 생겼습니다. "
                "서버 창(검은 창)의 마지막 메시지를 확인해 주세요.",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )

    # PWA(브라우저에서 앱처럼 설치) 관련 파일은 최상위 경로에서 찾는 것이 규칙이다
    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest() -> FileResponse:
        return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "icons" / "icon-192.png", media_type="image/png")

    # 나머지 모든 경로는 화면 파일. 반드시 맨 마지막에 등록해야 위 라우트를 가리지 않는다.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


app = create_app()
