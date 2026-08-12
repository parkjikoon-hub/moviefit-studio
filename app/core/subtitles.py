"""자막 세그먼트를 만들고, 줄바꿈하고, SRT/VTT로 주고받는 곳 (F-11, F-03, F-04).

이 파일은 순수 파이썬 계산만 한다. 음성인식 라이브러리나 FFmpeg을 부르지 않는다.
그래서 모델 없이도 빠르게 시험해 볼 수 있다.

세그먼트(자막 한 덩어리)의 모양은 TECH_SPEC 5절의 프로젝트 JSON과 똑같다:

    {"id": "s001", "start": 1.20, "end": 3.85, "text": "안녕하세요, 피엘에스입니다."}

분할 규칙 (TECH_SPEC 8절):
    ① 문장이 끝나는 자리(마침표·물음표·느낌표, 한국어 종결어미)에서 먼저 끊는다
    ② 그래도 길면 쉼표·세미콜론 같은 절 구분 자리에서 끊는다
    ③ 그래도 길면 어절(띄어쓰기) 단위로 끊는다 — 단어 중간은 절대 자르지 않는다
    길이 한도는 style_map의 max_chars(한 줄 글자수) × max_lines(줄 수)다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Iterator

import pysubs2

# 문장이 끝났다고 볼 문장부호
SENTENCE_MARKS = (".", "!", "?", "。", "！", "？", "…", "‥")

# 절이 끊기는 자리 (문장 끝은 아니지만 여기서 끊으면 자연스럽다)
CLAUSE_MARKS = (",", "，", "、", ";", "；", ":", "：")

# 한국어 종결어미 — 음성인식이 마침표를 빠뜨렸을 때의 보조 신호.
# 어절(띄어쓰기 단위) 맨 끝에서만 따진다. 예: "있다는"은 "있다"로 끝나지 않으므로 걸리지 않는다.
KOREAN_ENDINGS = (
    "습니다", "ㅂ니다", "입니다", "십시오", "세요", "예요", "이에요",
    "네요", "군요", "지요", "어요", "아요", "해요",
    "한다", "이다", "있다", "없다", "같다",
)

# 문장부호 뒤에 붙어 오는 닫는 기호들 (판정 전에 떼어 낸다)
_TRAILING = "\"'”’』」)]》〉>"


# ── 작은 도우미들 ──────────────────────────────────────────
def _tail(text: str) -> str:
    """닫는 따옴표·괄호를 떼어 낸 어절의 끝부분."""
    return text.strip().rstrip(_TRAILING)


def is_sentence_end(text: str) -> bool:
    """이 어절에서 문장이 끝났다고 볼 수 있는가."""
    tail = _tail(text)
    if not tail:
        return False
    return tail.endswith(SENTENCE_MARKS) or tail.endswith(KOREAN_ENDINGS)


def is_clause_end(text: str) -> bool:
    """이 어절에서 절이 끊긴다고 볼 수 있는가 (쉼표 등)."""
    tail = _tail(text)
    return bool(tail) and tail.endswith(CLAUSE_MARKS)


def _join(words: Iterable[dict[str, Any]]) -> str:
    """단어 목록을 사람이 읽는 한 줄 문장으로 잇는다.

    음성인식이 주는 단어는 보통 앞에 공백이 붙어 있다(" 안녕하세요"). 하지만
    직접 만든 단어 목록에는 없을 수도 있다. 양쪽 다 자연스럽게 이어지도록
    "이미 공백이 있으면 그대로, 없으면 하나 넣기"로 처리한다.
    """
    out = ""
    for item in words:
        piece = str(item.get("word", ""))
        if not out:
            out = piece.lstrip()
        elif out.endswith(" ") or piece.startswith(" "):
            out += piece
        else:
            out += " " + piece
    return re.sub(r"[ \t]+", " ", out).strip()


def _hard_break(token: str, max_chars: int) -> list[str]:
    """한 어절이 통째로 한 줄보다 길 때 글자 수로 강제로 자른다.

    한국어는 '초등학교운동장에서' 처럼 띄어쓰기 없이 긴 덩어리가 흔하다.
    이때 자르지 않으면 화면 밖으로 삐져나가므로 어쩔 수 없이 글자 단위로 끊는다.
    """
    return [token[i : i + max_chars] for i in range(0, len(token), max_chars)] or [""]


def wrap_text(text: str, max_chars: int = 20, max_lines: int = 2) -> list[str]:
    """자막 한 덩어리를 화면에 올릴 여러 줄로 나눈다 (어절 단위 우선).

    - 한 줄은 max_chars 글자를 넘지 않는다.
    - 줄 수는 max_lines를 넘지 않는다. 그래도 넘칠 만큼 긴 글이 들어오면
      (사용자가 직접 길게 타이핑한 경우) 글자를 버리지 않고 마지막 줄에 몰아넣는다.
    """
    max_chars = max(1, int(max_chars))
    max_lines = max(1, int(max_lines))

    lines: list[str] = []
    current = ""
    for token in text.split():
        pieces = [token] if len(token) <= max_chars else _hard_break(token, max_chars)
        for piece in pieces:
            if not current:
                current = piece
            elif len(current) + 1 + len(piece) <= max_chars:
                current += " " + piece
            else:
                lines.append(current)
                current = piece
    if current:
        lines.append(current)
    if not lines:
        return [""]

    if len(lines) > max_lines:
        # 넘치는 줄은 마지막 줄에 이어 붙인다 (내용을 잃는 것보다 낫다)
        lines = lines[: max_lines - 1] + [" ".join(lines[max_lines - 1 :])]
    return lines


def fits(text: str, max_chars: int, max_lines: int) -> bool:
    """이 문장이 max_lines줄 × max_chars글자 안에 깔끔히 들어가는가."""
    lines = wrap_text(text, max_chars, max_lines)
    return len(lines) <= max_lines and all(len(line) <= max_chars for line in lines)


# ── 세그먼트 분할 (F-11) ───────────────────────────────────
def _group(words: list[dict[str, Any]], is_break) -> Iterator[list[dict[str, Any]]]:
    """조건에 맞는 어절 '뒤에서' 끊어 덩어리들을 만든다."""
    buf: list[dict[str, Any]] = []
    for word in words:
        buf.append(word)
        if is_break(str(word.get("word", ""))):
            yield buf
            buf = []
    if buf:
        yield buf


def _pack(words: list[dict[str, Any]], max_chars: int, max_lines: int) -> list[list[dict[str, Any]]]:
    """길이만 보고 어절 단위로 욕심껏 채워 나눈다. 단어 중간은 자르지 않는다."""
    chunks: list[list[dict[str, Any]]] = []
    buf: list[dict[str, Any]] = []
    for word in words:
        if buf and not fits(_join(buf + [word]), max_chars, max_lines):
            chunks.append(buf)
            buf = [word]
        else:
            buf.append(word)
    if buf:
        chunks.append(buf)
    return chunks


def _make(index: int, words: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": f"s{index:03d}",
        "start": round(float(words[0].get("start", 0.0)), 2),
        "end": round(float(words[-1].get("end", 0.0)), 2),
        "text": _join(words),
    }


def split_into_segments(
    words: list[dict[str, Any]],
    max_chars: int = 20,
    max_lines: int = 2,
) -> list[dict[str, Any]]:
    """단어별 시각 목록을 자막 세그먼트 목록으로 바꾼다 (F-11).

    words: [{"word": "안녕하세요", "start": 0.0, "end": 0.8}, ...]
    돌려주는 값: [{"id": "s001", "start": 0.0, "end": 0.8, "text": "안녕하세요"}, ...]
    """
    max_chars = max(1, int(max_chars))
    max_lines = max(1, int(max_lines))

    clean = [w for w in words if str(w.get("word", "")).strip()]
    if not clean:
        return []

    pieces: list[list[dict[str, Any]]] = []
    # ① 문장 단위로 먼저 자른다. 문장 경계는 절대 합치지 않는다.
    for sentence in _group(clean, is_sentence_end):
        if fits(_join(sentence), max_chars, max_lines):
            pieces.append(sentence)
            continue

        # ② 문장이 너무 길면 절 단위로 자르고, 들어가는 만큼 다시 붙인다.
        sentence_pieces: list[list[dict[str, Any]]] = []
        for clause in _group(sentence, is_clause_end):
            # ③ 절 하나가 여전히 길면 길이로 자른다.
            chunks = [clause] if fits(_join(clause), max_chars, max_lines) else _pack(clause, max_chars, max_lines)
            for chunk in chunks:
                if sentence_pieces and fits(_join(sentence_pieces[-1] + chunk), max_chars, max_lines):
                    sentence_pieces[-1] = sentence_pieces[-1] + chunk
                else:
                    sentence_pieces.append(chunk)
        pieces.extend(sentence_pieces)

    return [_make(i, piece) for i, piece in enumerate(pieces, start=1)]


# ── 사용자 사전 (F-12) ─────────────────────────────────────
def apply_corrections(
    segments: list[dict[str, Any]],
    corrections: list[dict[str, str]] | None,
) -> list[dict[str, Any]]:
    """사용자 사전대로 글자를 바꿔 준다. 예: {"from": "피엘에스", "to": "PLS"}.

    음성인식은 고유명사·전문용어에 약하다(TECH_SPEC R2). 매번 손으로 고치지 않도록
    자주 틀리는 말을 사전에 넣어 두면 인식 직후 자동으로 치환한다.
    """
    if not corrections:
        return segments
    rules = [(str(r.get("from", "")), str(r.get("to", ""))) for r in corrections]
    rules = [(src, dst) for src, dst in rules if src]
    for seg in segments:
        text = seg.get("text", "")
        for src, dst in rules:
            text = text.replace(src, dst)
        seg["text"] = text
    return segments


# ── SRT/VTT 내보내기 (F-03) ────────────────────────────────
def _to_ssafile(
    segments: list[dict[str, Any]],
    max_chars: int | None = None,
    max_lines: int = 2,
) -> pysubs2.SSAFile:
    """세그먼트 목록을 pysubs2 자막 객체로 옮긴다.

    max_chars를 주면 저장할 때도 화면과 똑같이 줄바꿈해서 넣는다.
    """
    subs = pysubs2.SSAFile()
    for seg in segments:
        text = str(seg.get("text", ""))
        if max_chars:
            text = "\n".join(wrap_text(text, max_chars, max_lines))
        event = pysubs2.SSAEvent(
            start=pysubs2.make_time(s=float(seg.get("start", 0.0))),
            end=pysubs2.make_time(s=float(seg.get("end", 0.0))),
        )
        event.plaintext = text  # 줄바꿈을 자막 형식에 맞게 알아서 바꿔 준다
        subs.append(event)
    return subs


def to_srt(segments: list[dict[str, Any]], max_chars: int | None = None, max_lines: int = 2) -> str:
    """SRT 형식 문자열."""
    return _to_ssafile(segments, max_chars, max_lines).to_string("srt")


def to_vtt(segments: list[dict[str, Any]], max_chars: int | None = None, max_lines: int = 2) -> str:
    """WebVTT 형식 문자열."""
    return _to_ssafile(segments, max_chars, max_lines).to_string("vtt")


def save_srt(
    segments: list[dict[str, Any]],
    path: str | Path,
    max_chars: int | None = None,
    max_lines: int = 2,
) -> Path:
    """SRT 파일로 저장한다 (UTF-8)."""
    return _save(segments, path, "srt", max_chars, max_lines)


def save_vtt(
    segments: list[dict[str, Any]],
    path: str | Path,
    max_chars: int | None = None,
    max_lines: int = 2,
) -> Path:
    """WebVTT 파일로 저장한다 (UTF-8)."""
    return _save(segments, path, "vtt", max_chars, max_lines)


def _save(
    segments: list[dict[str, Any]],
    path: str | Path,
    fmt: str,
    max_chars: int | None,
    max_lines: int,
) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _to_ssafile(segments, max_chars, max_lines).save(str(out), encoding="utf-8", format_=fmt)
    return out


# ── SRT/VTT 가져오기 (F-04) ────────────────────────────────
class SubtitleImportError(Exception):
    """자막 파일을 읽지 못했을 때."""


def load_subtitle_file(path: str | Path) -> list[dict[str, Any]]:
    """SRT·VTT·ASS 파일을 읽어 세그먼트 목록으로 돌려준다.

    파일 안의 순서대로 s001부터 번호를 다시 매긴다.
    """
    src = Path(path)
    if not src.is_file():
        raise SubtitleImportError(f"자막 파일이 없습니다: {src}")

    try:
        subs = pysubs2.load(str(src), encoding="utf-8")
    except UnicodeDecodeError:
        # 윈도우에서 만든 옛 자막은 cp949(euc-kr)인 경우가 많다
        try:
            subs = pysubs2.load(str(src), encoding="cp949")
        except Exception as exc:
            raise SubtitleImportError(f"자막 파일의 글자 인코딩을 알 수 없습니다: {src.name}") from exc
    except Exception as exc:
        raise SubtitleImportError(f"자막 파일을 읽지 못했습니다: {src.name} ({exc})") from exc

    segments: list[dict[str, Any]] = []
    for event in subs:
        if event.is_comment:
            continue
        text = " ".join(event.plaintext.split())
        if not text:
            continue
        segments.append(
            {
                "id": f"s{len(segments) + 1:03d}",
                "start": round(event.start / 1000.0, 2),
                "end": round(event.end / 1000.0, 2),
                "text": text,
            }
        )
    return segments
