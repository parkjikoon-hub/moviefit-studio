"""오래 걸리는 작업을 뒤에서 돌리고 진행률을 알려 주는 장치.

왜 필요한가 (TECH_SPEC 3절 R3): 음성인식과 영상 렌더링은 몇 분씩 걸린다.
이걸 그냥 처리하면 화면이 통째로 멈춰 사용자는 프로그램이 죽은 줄 안다.
그래서 작업을 별도 스레드에 맡기고 즉시 작업 번호(job_id)를 돌려준 뒤,
화면이 1초마다 진행률을 물어보게 한다.

쓰는 법:

    def 오래_걸리는_일(report, ...):
        report(0.3, "절반쯤 왔습니다")
        ...
        return {"결과": ...}

    job_id = jobs.submit("stt", 오래_걸리는_일, ...)
    jobs.get(job_id)   # {"status": "running", "progress": 0.3, ...}
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

# 상태값
PENDING = "pending"
RUNNING = "running"
DONE = "done"
ERROR = "error"
CANCELLED = "cancelled"

# 끝난 작업을 몇 개까지 들고 있을지 (메모리 정리용)
KEEP_FINISHED = 40


class JobCancelled(Exception):
    """사용자가 취소를 눌렀을 때 작업 함수 안에서 올라온다."""


@dataclass
class Job:
    id: str
    kind: str  # "stt" | "tts" | "render" ...
    label: str  # 화면에 보여줄 한국어 설명
    status: str = PENDING
    progress: float = 0.0  # 0.0 ~ 1.0
    message: str = "준비 중입니다…"
    result: Any = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(sep=" ", timespec="seconds"))
    finished_at: str | None = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "progress": round(self.progress, 4),
            "percent": round(self.progress * 100),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _prune() -> None:
    """끝난 작업이 너무 쌓이면 오래된 것부터 지운다."""
    finished = [j for j in _jobs.values() if j.status in (DONE, ERROR, CANCELLED)]
    if len(finished) <= KEEP_FINISHED:
        return
    finished.sort(key=lambda j: j.finished_at or j.created_at)
    for job in finished[: len(finished) - KEEP_FINISHED]:
        _jobs.pop(job.id, None)


def submit(kind: str, label: str, fn: Callable[..., Any], **kwargs: Any) -> str:
    """작업을 뒤에서 시작하고 작업 번호를 즉시 돌려준다.

    fn의 첫 번째 인자로 report(progress, message) 함수가 전달된다.
    fn 안에서 취소 여부를 확인하려면 report()를 부르면 된다 — 취소되었으면
    JobCancelled 예외가 올라간다.
    """
    job = Job(id=uuid.uuid4().hex[:12], kind=kind, label=label)

    with _lock:
        _jobs[job.id] = job
        _prune()

    def report(progress: float, message: str | None = None) -> None:
        if job._cancel.is_set():
            raise JobCancelled()
        job.progress = max(0.0, min(1.0, float(progress)))
        if message is not None:
            job.message = message

    def runner() -> None:
        job.status = RUNNING
        job.message = "시작합니다…"
        try:
            job.result = fn(report, **kwargs)
            job.status = DONE
            job.progress = 1.0
            job.message = "완료되었습니다."
        except JobCancelled:
            job.status = CANCELLED
            job.message = "취소되었습니다."
        except Exception as exc:
            job.status = ERROR
            # 사용자에게 보여줄 메시지는 예외에 담긴 한국어 문장을 그대로 쓴다
            job.error = str(exc) or f"{type(exc).__name__}"
            job.message = "오류가 발생했습니다."
            traceback.print_exc()
        finally:
            job.finished_at = datetime.now().isoformat(sep=" ", timespec="seconds")

    threading.Thread(target=runner, name=f"job-{kind}-{job.id}", daemon=True).start()
    return job.id


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def cancel(job_id: str) -> bool:
    """작업에 취소 신호를 보낸다. 실제로 멈추는 시점은 작업 함수가 report()를 부를 때다."""
    job = _jobs.get(job_id)
    if job is None or job.status in (DONE, ERROR, CANCELLED):
        return False
    job._cancel.set()
    job.message = "취소하는 중입니다…"
    return True


def is_cancelled(job_id: str) -> bool:
    job = _jobs.get(job_id)
    return bool(job and job._cancel.is_set())


def list_active() -> list[dict[str, Any]]:
    return [j.to_dict() for j in _jobs.values() if j.status in (PENDING, RUNNING)]
