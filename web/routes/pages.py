import os
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

_VALID_THEMES = {"light", "dark"}


def _read_app_version() -> str:
    try:
        data = tomllib.loads(
            Path("pyproject.toml").read_text(encoding="utf-8")
        )
        return data.get("project", {}).get("version") or "dev"
    except Exception:
        return "dev"


_APP_VERSION = _read_app_version()


def _theme_default() -> str:
    value = (os.environ.get("ADVISORY_THEME_DEFAULT") or "").strip().lower()
    return value if value in _VALID_THEMES else "light"


@router.get("/")
def chat_page(request: Request):
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "page_title": "Student Advisory Chat",
            "theme_default": _theme_default(),
            "app_version": _APP_VERSION,
        },
    )
