"""목소리 언어 점검 — 목록에 보이는 목소리를 **정말로 들을 수 있는가**.

왜 이 점검이 생겼나 (2026-08-14):
미리듣기가 어떤 목소리에게든 **한국어 문장을 고정으로** 보내고 있었다. 그런데
한국어를 읽을 수 있는 목소리는 322개 중 **15개뿐**이다(한국어 전용 3 + 다국어 12).
나머지 307개는 한국어 글을 받으면 마이크로소프트 서버가 소리를 하나도 돌려주지
않는다(`NoAudioReceived`). 사용자에게는 이렇게 보였다:

    "나레이션을 만들지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요."

인터넷은 멀쩡했다. **오류 문구가 엉뚱한 곳을 가리켜** 될 때까지 다시 누르게 만들었다.

사용법:
    1) 서버를 띄운다      python -m app --port 8766
    2) 이 파일을 실행한다  set MOVIEFIT_TEST_URL=http://127.0.0.1:8766
                          python tests/voice_language_test.py

    ※ 인터넷이 필요하다 (목소리를 실제로 만들어 보므로).

무엇을 보는가 — 네 가지:
  ① 여러 나라 목소리가 **실제로 소리를 돌려주는가** (파일 크기로 잰다)
  ② 한국어를 못 읽는 목소리에 한국어 글을 주면 **원인을 정확히 말하는가**
     ("인터넷"이 아니라 "한국어를 읽지 못합니다")
  ③ 견본 문장이 언어마다 **실제로 다른가** (전부 영어면 고친 뜻이 없다)
  ④ 화면(app.js)에 견본 문장이 **다시 복사되어 있지 않은가**
     — 서버만 고치고 화면에 사본이 남으면 고친 것이 무효가 된다
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("MOVIEFIT_TEST_URL", "http://127.0.0.1:8765").rstrip("/")

passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passed if ok else failed).append(name)
    mark = "  OK  " if ok else " 실패 "
    print(f"[{mark}] {name}" + (f"   {detail}" if detail else ""))


def _preview(voice: str, text: str | None = None) -> tuple[int, bytes, str]:
    """미리듣기를 부른다 → (응답코드, 소리 바이트, 오류 메시지)."""
    body: dict[str, object] = {"voice": voice}
    if text is not None:
        body["text"] = text
    req = urllib.request.Request(
        f"{BASE}/api/tts/preview",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as res:
            return res.status, res.read(), ""
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            msg = json.loads(raw).get("detail", raw)
        except Exception:
            msg = raw
        return exc.code, b"", msg


# ── ① 여러 나라 목소리가 실제로 소리를 돌려주는가 ─────────────
print("\n① 나라별 목소리를 실제로 들어 본다 (견본 문장은 서버가 고른다)\n")

VOICES = [
    ("ko-KR-SunHiNeural", "한국어 전용"),
    ("ko-KR-InJoonNeural", "한국어 전용"),
    ("en-US-AvaMultilingualNeural", "다국어"),
    ("de-DE-SeraphinaMultilingualNeural", "다국어"),
    ("en-US-JennyNeural", "영어 전용"),
    ("ja-JP-NanamiNeural", "일본어 전용"),
    ("zh-CN-XiaoxiaoNeural", "중국어 전용"),
    ("fr-FR-DeniseNeural", "프랑스어 전용"),
    ("es-ES-ElviraNeural", "스페인어 전용"),
    ("af-ZA-AdriNeural", "견본 없는 언어"),
]

for voice, kind in VOICES:
    status, audio, err = _preview(voice)
    check(
        f"미리듣기 · {kind} · {voice}",
        status == 200 and len(audio) > 2000,
        f"{len(audio):,}바이트" if audio else f"HTTP {status} — {err[:60]}",
    )

# ── ② 원인을 정확히 말하는가 ──────────────────────────────
print("\n② 한국어를 못 읽는 목소리에 한국어 글을 주면 무엇이라 말하는가\n")

status, audio, err = _preview("fr-FR-DeniseNeural", "안녕하세요. 오늘 소식입니다.")
check("한국어 글 + 프랑스어 목소리 → 실패로 처리된다", status != 200, f"HTTP {status}")
check("원인을 '한국어를 읽지 못합니다'로 알려 준다", "한국어를 읽지 못합니다" in err, err[:70])
check("엉뚱하게 '인터넷'을 탓하지 않는다", "인터넷" not in err, err[:70])
check("어느 나라 목소리인지 알려 준다", "프랑스어" in err, err[:70])
check("무엇을 고르면 되는지 알려 준다", "한국어 가능" in err, err[:70])
check("안내의 첫 글자가 한글이다", bool(err) and "가" <= err[0] <= "힣", err[:20])

# 한국어 목소리로는 같은 글이 정상 동작해야 한다 (위 실패가 글 탓이 아님을 증명)
status, audio, _ = _preview("ko-KR-SunHiNeural", "안녕하세요. 오늘 소식입니다.")
check("같은 글을 한국어 목소리에 주면 정상", status == 200 and len(audio) > 2000,
      f"{len(audio):,}바이트")

# ── ③ 견본 문장이 언어마다 실제로 다른가 ──────────────────
print("\n③ 견본 문장이 언어마다 실제로 다른가 (전부 영어면 고친 뜻이 없다)\n")

sys.path.insert(0, str(ROOT))
from app.core.tts.base import SAMPLE_TEXTS, sample_text_for  # noqa: E402

pairs = [
    ("ko-KR-SunHiNeural", "ko"),
    ("ja-JP-NanamiNeural", "ja"),
    ("fr-FR-DeniseNeural", "fr"),
    ("zh-CN-XiaoxiaoNeural", "zh"),
]
for voice, lang in pairs:
    check(f"{lang} 목소리는 {lang} 견본을 받는다",
          sample_text_for(voice) == SAMPLE_TEXTS[lang],
          sample_text_for(voice)[:30])

check("견본 문장들이 서로 다르다",
      len({sample_text_for(v) for v, _ in pairs}) == len(pairs))
check("견본 없는 언어는 영어로 대신한다",
      sample_text_for("af-ZA-AdriNeural") == SAMPLE_TEXTS["en"])

# ── ④ 화면에 견본 문장 사본이 남아 있지 않은가 ────────────
print("\n④ 화면(app.js)에 견본 문장이 다시 복사되어 있지 않은가\n")

app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
check("app.js 가 한국어 견본 문장을 직접 들고 있지 않다",
      "이 목소리로 나레이션을 만들어 드립니다" not in app_js,
      "사본이 남아 있으면 서버 수정이 무효가 된다")

# 목록 자체도 확인 — 한국어 가능 개수가 실제와 맞는가
try:
    with urllib.request.urlopen(f"{BASE}/api/tts/voices", timeout=60) as res:
        data = json.loads(res.read().decode())
    check("목소리 목록을 받아온다", data.get("total", 0) > 100, f"{data.get('total')}개")
    check("한국어 가능 개수를 세어 알려 준다",
          data.get("korean_capable_count", 0) >= 10,
          f"{data.get('korean_capable_count')}개 / 전체 {data.get('total')}개")
except Exception as exc:  # 목록 실패는 위 항목들과 별개로 표시한다
    check("목소리 목록을 받아온다", False, f"{type(exc).__name__}")

# ── ⑤ 음성 서버가 거절할 때 — 다시 시도하는가, 원인을 바로 말하는가 ──
# 2026-11-04 배포 전 점검에서 마이크로소프트 서버가 한 번 503(잠시 이용할 수 없음)을
# 돌려줘 나레이션 전체가 멈췄다. 직후에는 정상이었다. 문장이 많을수록 이런 순간을
# 만날 확률이 커지는데, 전에는 한 번에 포기하고 "인터넷 연결을 확인하세요"라고 했다.
# 진짜 서버가 실패해 주길 기다릴 수는 없으므로, 앞의 몇 번만 거절하는 가짜를 끼운다.
print("\n⑤ 음성 서버가 거절하면 다시 시도하고, 원인을 바로 말하는가\n")

import asyncio  # noqa: E402

import edge_tts  # noqa: E402

from app.core.tts import edge as edge_module  # noqa: E402
from app.core.tts import get_engine  # noqa: E402
from app.core.tts.base import TTSError  # noqa: E402


class _Refused(Exception):
    """aiohttp 의 WSServerHandshakeError 처럼 status 를 들고 있는 거절."""

    def __init__(self, status: int):
        super().__init__(f"{status}, message='Invalid response status'")
        self.status = status


_REAL_COMMUNICATE = edge_tts.Communicate


def _try_with_refusals(times: int, error: Exception) -> tuple[str, int, float]:
    """앞의 times 번은 error 로 거절하고, 그 뒤로는 진짜 서버에 묻는다.
    돌려주는 것: (결과 — 'ok' 또는 안내 문구, 서버에 물은 횟수, 소리 길이)"""
    calls = {"n": 0}

    class FakeCommunicate:
        def __init__(self, *args, **kwargs):
            self._args, self._kwargs = args, kwargs

        async def stream(self):
            calls["n"] += 1
            if calls["n"] <= times:
                raise error
            async for chunk in _REAL_COMMUNICATE(*self._args, **self._kwargs).stream():
                yield chunk

    edge_tts.Communicate = FakeCommunicate
    saved_delays = getattr(edge_module, "RETRY_DELAYS", ())
    edge_module.RETRY_DELAYS = tuple(0.0 for _ in saved_delays)  # 점검은 기다리지 않는다
    try:
        result = asyncio.run(get_engine("edge").synthesize("안녕하세요. 시험입니다.", "ko-KR-SunHiNeural"))
        return "ok", calls["n"], result.duration
    except TTSError as exc:
        return str(exc), calls["n"], 0.0
    finally:
        edge_tts.Communicate = _REAL_COMMUNICATE
        edge_module.RETRY_DELAYS = saved_delays


out, n, dur = _try_with_refusals(2, _Refused(503))
check("503 이 두 번 와도 세 번째에 성공한다", out == "ok" and dur > 0.3, f"{n}번 물음 · {dur:.2f}초 · {out[:40]}")
check("성공할 때까지 정확히 세 번 물었다", n == 3, f"{n}번")

out, n, _ = _try_with_refusals(99, _Refused(503))
check("503 이 계속되면 세 번에서 멈춘다", n == 3, f"{n}번")
check("계속되는 503 → '음성 서버' 탓이라고 말한다", "음성 서버" in out, out[:70])
check("계속되는 503 → 엉뚱하게 '인터넷'을 탓하지 않는다", "인터넷" not in out, out[:70])
check("계속되는 503 → 안내의 첫 글자가 한글이다", bool(out) and "가" <= out[0] <= "힣", out[:20])

out, n, _ = _try_with_refusals(99, _Refused(403))
check("403(판이 낡아 거절) → 다시 묻지 않는다", n == 1, f"{n}번")
check("403 → 새 판을 받으라고 말한다", "새 판" in out, out[:70])
check("403 → 엉뚱하게 '인터넷'을 탓하지 않는다", "인터넷" not in out, out[:70])

out, n, _ = _try_with_refusals(99, OSError("연결 실패"))
check("서버에 닿지도 못하면 → 다시 묻지 않는다", n == 1, f"{n}번")
check("서버에 닿지도 못하면 → 그때는 '인터넷'을 확인하라고 한다", "인터넷" in out, out[:70])

# ── 정리 ─────────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"통과 {len(passed)}개 / 실패 {len(failed)}개  (겨냥한 서버: {BASE})")
if failed:
    print("\n실패한 항목:")
    for name in failed:
        print(f"  - {name}")
print("=" * 60)
sys.exit(1 if failed else 0)
