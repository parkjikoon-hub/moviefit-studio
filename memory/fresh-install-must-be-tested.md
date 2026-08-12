개발 컴퓨터에서 잘 도는 것은 "내려받은 사람 컴퓨터에서 도는 것"을 전혀 보장하지 않는다. 배포하는 프로그램은 반드시 빈 환경에서 처음부터 설치해 봐야 한다.

상황 (2026-08-12): Phase 0~3을 끝내고 자동 점검 123개 항목을 통과시킨 뒤 GitHub와
Vercel에 공개까지 했다. 그 상태에서 "내려받아 설치하면 정상 동작하느냐"는 질문을 받고
처음으로 빈 가상환경에 clone 해서 돌려 보았더니 **첫 실행이 통째로 실패했다.**

    UnicodeDecodeError: 'cp949' codec can't decode byte 0xec in position 18

원인: requirements.txt에 한글 주석이 있는데 BOM이 없었다. pip의 auto_decode는
BOM이 있으면 그것을 따르고 없으면 locale 기본 인코딩(한국 윈도우=cp949)으로 읽는다.
그래서 파일을 읽는 순간 죽고, 부품이 하나도 설치되지 않았다.

해결: requirements.txt를 **UTF-8 BOM으로 저장**한다. 한글 설명을 지울 필요가 없다.
    $text = [IO.File]::ReadAllText(path, [Text.Encoding]::UTF8)
    [IO.File]::WriteAllText(path, $text, (New-Object Text.UTF8Encoding($true)))
BOM은 git clone을 거쳐도 살아남는다(확인함). .gitattributes의 `*.txt text eol=lf`는
줄바꿈만 바꾸고 BOM은 건드리지 않는다.

함께 발견된 것 (같은 뿌리):
- 자막 번인용 폰트(assets/fonts/*.otf)는 용량 때문에 .gitignore로 빼 두었는데
  run.bat이 이를 받아 주지 않았다. 내려받은 사람은 화면 미리보기와 **다른 글꼴**로
  자막이 새겨졌다. (코드 주석은 "네모(□)가 된다"고 경고했지만 실제로는 윈도우
  기본 글꼴로 대체되었다 — 경고 문구가 실제 증상과 달라서 더 못 알아챘다)
  → tools/launch.py에 ensure_fonts()를 넣어 첫 실행 때만 받게 했다.
- 목소리 견본 mp3 7개가 저장소 맨 위에 실수로 커밋되어 공개되어 있었다.
  → git rm --cached 로 내리고 .gitignore에 `/*.mp3` `/*.wav` `/*.mp4`를 넣었다.

**왜 이 결함들을 123개 자동 점검이 못 잡았나**: 전부 개발 컴퓨터에서는 실행되지
않는 경로였다. 부품이 이미 깔려 있으니 설치 단계가 통째로 건너뛰어졌고, 폰트도
이미 있으니 없는 상황이 만들어지지 않았다. 테스트는 "있는 것"만 확인할 수 있다.

그래서 앞으로 지킬 것:
1. 배포 대상 프로그램은 **빈 venv + 새 clone**으로 첫 실행을 반드시 시험한다.
   `git clone <repo> 새폴더 && python -m venv .venv && .venv\Scripts\python tools\launch.py`
2. .gitignore로 뺀 파일이 있으면, 그것을 **자동으로 받아 오는 경로가 실제로
   호출되는지** 확인한다. 안내 문구만 있고 아무도 부르지 않는 스크립트가 되기 쉽다.
3. 소개 사이트·README에 적은 설치 절차는 그 절차 그대로 밟아 검증한다.
