"""오래 걸리는 작업의 진행률 조회 API.

화면은 작업을 시작한 뒤 여기를 1초마다 물어보며 진행률 막대를 갱신한다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.core import jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다. 프로그램을 다시 켜셨다면 작업이 사라집니다.")
    return job.to_dict()


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    if not jobs.cancel(job_id):
        raise HTTPException(400, "이미 끝났거나 취소할 수 없는 작업입니다.")
    return {"cancelled": True, "id": job_id}


@router.get("")
def list_jobs() -> dict[str, Any]:
    """지금 돌아가고 있는 작업 목록."""
    return {"jobs": jobs.list_active()}
