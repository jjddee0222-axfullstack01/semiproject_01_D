"""
프로젝트 최상위 폴더용 실행 파일

실제 서버 코드는 backend/main.py 에 있습니다.
이 파일 덕분에 최상위 폴더에서도 아래 명령이 그대로 동작합니다.
    uvicorn main:app --reload
    python main.py
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"

# backend 폴더를 모듈 검색 경로에 추가 → backend/main.py 를 'main' 이 아닌 'backend.main' 으로 불러옴
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.main import app  # noqa: E402,F401  (uvicorn 이 이 app 을 사용)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", app_dir=str(ROOT_DIR), reload=True,
                reload_dirs=[str(BACKEND_DIR)])
