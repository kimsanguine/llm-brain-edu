"""uv run python -m wiki_app — localhost:8000에서 서버 시작."""
import uvicorn

from wiki_app.api import create_app


def main():
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
