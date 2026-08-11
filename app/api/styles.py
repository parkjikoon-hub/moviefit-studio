"""자막 스타일 관련 API — 프리셋 목록, 글꼴 목록, 사용자 프리셋 저장."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import ROOT_DIR
from app.core import fonts as fonts_mod
from app.core import style_map

router = APIRouter(prefix="/api/styles", tags=["styles"])

# 사용자가 만든 프리셋은 프로젝트와 무관하게 프로그램 전체에서 공유한다
USER_PRESETS_FILE = ROOT_DIR / "projects" / "_user_presets.json"


def _load_user_presets() -> list[dict[str, Any]]:
    if not USER_PRESETS_FILE.exists():
        return []
    try:
        return json.loads(USER_PRESETS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_user_presets(items: list[dict[str, Any]]) -> None:
    USER_PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USER_PRESETS_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@router.get("/presets")
def get_presets() -> dict[str, Any]:
    """기본 프리셋 5종 + 사용자가 저장한 프리셋."""
    return {"builtin": style_map.preset_list(), "user": _load_user_presets()}


class SavePresetRequest(BaseModel):
    name: str
    style: dict[str, Any]


@router.post("/presets", status_code=201)
def save_preset(req: SavePresetRequest) -> dict[str, Any]:
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "프리셋 이름을 입력해 주세요.")

    items = _load_user_presets()
    entry = {
        "key": f"user:{name}",
        "label": name,
        "desc": "내가 저장한 프리셋",
        "style": style_map.normalize(req.style),
    }
    # 같은 이름이 있으면 덮어쓴다
    items = [i for i in items if i["label"] != name]
    items.append(entry)
    _save_user_presets(items)
    return entry


@router.delete("/presets/{name}", status_code=204)
def delete_preset(name: str) -> None:
    items = _load_user_presets()
    remaining = [i for i in items if i["label"] != name]
    if len(remaining) == len(items):
        raise HTTPException(404, f"'{name}' 프리셋을 찾을 수 없습니다.")
    _save_user_presets(remaining)


@router.get("/fonts")
def get_fonts() -> dict[str, Any]:
    """자막에 쓸 수 있는 글꼴 목록."""
    return {"fonts": fonts_mod.list_fonts()}


@router.get("/default")
def get_default_style() -> dict[str, Any]:
    """스타일 기본값 (프론트엔드가 빠진 항목을 채울 때 쓴다)."""
    return style_map.DEFAULT_STYLE
