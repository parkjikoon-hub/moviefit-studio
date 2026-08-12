임베디드 파이썬으로 설치 파일을 만들 때, 동작을 좌우하는 것은 거의 전부 `python311._pth` 한 파일이다. 여기서 세 번 넘어졌다.

배경 (2026-08-12): "GitHub 다운로드·설치를 어려워하는 사람이 많다"는 요구로 설치 파일
하나(exe)를 만들기로 했다. PyInstaller 대신 **임베디드 파이썬을 통째로 넣는 방식**을 택했다.
음성인식 부품(ctranslate2, onnxruntime)은 exe 변환에서 오류가 잦은데, 임베디드 방식은
개발 환경과 똑같이 동작하기 때문이다. 이 판단 자체는 옳았다 — 부품 import는 한 번에 통과했다.

넘어진 곳 세 군데, 전부 `._pth`:

1. **`Lib` 를 빠뜨렸다** → `ModuleNotFoundError: No module named 'tkinter'`
   기본 `._pth`에는 `Lib`가 없다. `Lib\site-packages`만 넣으면 pip으로 설치한 부품은
   찾지만 표준 부품(tkinter 등)은 못 찾는다. 증상이 고약한 이유: **서버는 정상적으로
   뜨고 [영상 파일 선택하기] 버튼만 조용히 실패한다.** 기동 확인만으로는 못 잡는다.

2. **`..` 를 빠뜨렸다** → `No module named app`
   임베디드 파이썬은 격리 모드(isolated=1, safe_path=1)라 **현재 작업 폴더를 sys.path에
   넣지 않는다.** 일반 파이썬이 `-m app` 을 실행할 때 cwd를 넣어 주는 것과 다르다.
   `._pth`의 상대 경로는 python.exe가 있는 폴더 기준이므로, 앱이 그 상위에 있으면 `..`.
   PYTHONPATH로 우회하려 해도 소용없다 — `._pth`가 있으면 무시된다.

3. **BOM을 붙였다** → `Fatal Python error: init_fs_encoding` / `No module named 'encodings'`
   PowerShell의 `Set-Content -Encoding UTF8`은 BOM을 붙인다. 그러면 첫 줄이
   `﻿python311.zip`이 되어 표준 라이브러리 zip을 못 찾고 파이썬이 아예 시작하지 못한다.
   파이썬의 `write_text(encoding="utf-8")`은 BOM을 붙이지 않으므로 안전하다.

   같은 날 `requirements.txt`에는 **BOM을 붙여야** 했다([[fresh-install-must-be-tested]]).
   붙여야 하는 파일과 붙이면 안 되는 파일이 갈린다. 기준은 **누가 읽느냐**다:
   pip이 읽는 텍스트 → BOM 필요(없으면 cp949로 읽어 죽는다).
   파이썬 기동기가 읽는 `._pth` → BOM 금지(경로 문자열이 오염된다).

함께 확정된 것:
- **tkinter는 임베디드 파이썬에 없다.** 시스템 파이썬에서 `DLLs/_tkinter.pyd`,
  `DLLs/tcl86t.dll`, `DLLs/tk86t.dll`, `Lib/tkinter/`, `tcl/` 를 복사해 넣으면 동작한다(약 11MB).
  Tcl/Tk는 BSD 계열 라이선스라 재배포해도 된다.
- 설치 위치는 `{localappdata}\Programs`, `PrivilegesRequired=lowest`로 한다.
  `C:\Program Files`에 넣으면 projects/ 폴더 쓰기가 막히고 UAC 경고까지 뜬다.
  이렇게 하면 **코드를 하나도 고치지 않아도 되고 관리자 권한도 필요 없다.**
- FFmpeg은 full build(각 213MB)가 아니라 **essentials build**를 쓴다(각 98MB).
  자막 번인(libx264)·무음 감지·mp3 인코딩 모두 essentials로 충분하다.
- 음성인식 모델(486MB)은 넣지 않는다. 첫 사용 때 받게 두면 설치 파일이 700MB→200MB로 줄어든다.

교훈: 번들은 "부품이 import 되는가"로 끝나지 않는다. **실제 실행 경로를 끝까지 밟아야 한다.**
세 결함 중 둘은 import 확인만으로는 드러나지 않았다.
