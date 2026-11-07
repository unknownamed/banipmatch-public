"""python -m backend: 모의 API를 loopback·단일 프로세스로만 실행."""
import uvicorn

from backend.api.app import create_app
from backend.api.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    settings.check()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=8000, workers=1)


if __name__ == "__main__":
    main()
