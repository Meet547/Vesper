import uvicorn

from backend.app.config import get_settings


if __name__ == "__main__":
    settings = get_settings()
    # OAuth authorization codes arrive in the callback query string. Uvicorn's
    # default access log prints full URLs, so disable it to keep codes out of logs.
    uvicorn.run("backend.app.main:app", host=settings.app_host, port=settings.app_port,
                reload=True, access_log=False)
