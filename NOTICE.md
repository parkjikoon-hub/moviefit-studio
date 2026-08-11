# 제3자 고지 (Third-party notices)

MovieFit Studio 본체는 MIT License로 배포됩니다 ([LICENSE](LICENSE) 참고).
아래는 함께 쓰이는 외부 자산과 프로그램에 대한 고지입니다.

## 함께 배포되는 글꼴

**Pretendard** — `tools/fetch_font.py`를 실행하면 `assets/fonts/`에 내려받습니다.

- 만든 사람: 길형진 (orioncactus)
- 라이선스: SIL Open Font License 1.1 (재배포·임베딩 허용)
- 원본: <https://github.com/orioncactus/pretendard>

## 사용하는 외부 프로그램·라이브러리

| 이름 | 용도 | 라이선스 |
|---|---|---|
| FFmpeg | 영상·오디오 처리 (별도 설치, 이 저장소에 포함되지 않음) | LGPL 2.1+ / GPL 2+ (빌드에 따라 다름) |
| faster-whisper | 로컬 음성인식 | MIT |
| edge-tts | AI 나레이션 음성 생성 | LGPL 3.0 |
| FastAPI · uvicorn | 웹 서버 | MIT · BSD 3-Clause |
| pysubs2 | 자막 파일 처리 | MIT |
| Pillow | 아이콘 생성 | MIT-CMU |

## 상표

**CapCut**은 ByteDance Ltd.의 상표입니다.
본 프로젝트는 ByteDance와 아무런 관련이 없으며, 어떤 회사의 후원이나 승인도 받지 않았습니다.
CapCut의 아이콘·로고·그래픽 자산은 이 프로젝트에 일절 사용하지 않았습니다.
문서에서 CapCut을 언급하는 것은 기능 비교를 위한 사실 서술입니다.

## 나레이션 음성에 대한 고지

기본 나레이션은 Microsoft Edge의 신경망 음성을 `edge-tts`를 통해 사용합니다.
이는 마이크로소프트의 공식 공개 API가 아니므로, 서비스 제공자의 사정에 따라
예고 없이 동작하지 않을 수 있습니다. 이 경우를 대비해 음성 엔진은 교체 가능한
어댑터 구조(`app/core/tts/`)로 설계되어 있습니다.

생성한 음성의 상업적 이용 가능 여부는 각 음성 제공자의 이용약관을 따릅니다.
