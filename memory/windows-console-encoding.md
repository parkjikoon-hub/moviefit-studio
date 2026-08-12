윈도우 한글 명령창은 기본 인코딩이 cp949라서, 파이썬 print에 '—'(em dash) 같은 문자를 넣으면 UnicodeEncodeError로 프로그램이 즉사한다.

상황: `python -m app` 실행 시 시작 배너의 "MovieFit Studio — 자막·나레이션 스튜디오"를 출력하다가
`UnicodeEncodeError: 'cp949' codec can't encode character '—'` 로 서버가 뜨지도 못하고 종료됐다.
한글 자체는 cp949에 있어서 통과하는데, 유니코드 기호(—, ·, ✓, → 등)에서만 터진다.
그래서 "한글은 잘 나오는데?" 하고 방심하기 쉽다.

해결: 사용자에게 무언가를 print하는 모든 진입점 스크립트 맨 위에 아래를 넣는다.

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

적용한 곳: app/__main__.py, tools/check_env.py, tools/make_sample.py, tools/fetch_font.py.
run.bat에는 `chcp 65001`도 함께 넣어 두었다(둘 다 있어야 확실하다).

중요한 이유: 사용자가 run.bat을 더블클릭했을 때 아무 설명 없이 창이 닫히는 최악의 첫인상을 만든다.
새 진입점 스크립트를 만들 때마다 이 세 줄을 빠뜨리지 말 것.

같은 뿌리의 다른 함정 (2026-08-12 추가): cp949 문제는 **화면 출력만이 아니라 파일 읽기에서도**
터진다. pip이 requirements.txt의 한글 주석을 cp949로 읽으려다 죽어 첫 설치가 통째로 실패했다.
이쪽 해결책은 위 세 줄이 아니라 **파일을 UTF-8 BOM으로 저장**하는 것이다.
자세한 경위는 [[fresh-install-must-be-tested]] 참조.
정리하면: 내가 출력하는 글자는 stream.reconfigure로, 남이 읽는 파일은 BOM으로 지킨다.
