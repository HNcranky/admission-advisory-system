from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.routes.system import router as system_router
from web.routes.chat_api import router as chat_router
from web.routes.pages import router as page_router


def build_app() -> FastAPI:
    app = FastAPI(title="Student Advisory Chat")
    app.mount("/static", StaticFiles(directory="web/static"), name="static")
    app.include_router(system_router)
    app.include_router(chat_router)
    app.include_router(page_router)
    return app