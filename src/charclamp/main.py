from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from litestar import Litestar, Request
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.exceptions import NotAuthorizedException, PermissionDeniedException
from litestar.response import Redirect
from litestar.static_files import create_static_files_router
from litestar.template.config import TemplateConfig

from charclamp.web.auth import session_auth
from charclamp.web.controllers import AuthController, ClampController, ShiftController, TimelineController
from charclamp.web.time_filters import dt_display, dt_input_value, dt_iso

WEB_DIR = Path(__file__).parent / "web"
TEMPLATE_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
jinja_env.filters["dt_display"] = dt_display
jinja_env.filters["dt_input_value"] = dt_input_value
jinja_env.filters["dt_iso"] = dt_iso


def _redirect_login(_: Request, __: Exception) -> Redirect:
    return Redirect("/login")


app = Litestar(
    route_handlers=[
        TimelineController,
        AuthController,
        ClampController,
        ShiftController,
        create_static_files_router(path="/static", directories=[STATIC_DIR]),
    ],
    template_config=TemplateConfig(engine=JinjaTemplateEngine(engine_instance=jinja_env)),
    on_app_init=[session_auth.on_app_init],
    exception_handlers={
        NotAuthorizedException: _redirect_login,
        PermissionDeniedException: _redirect_login,
    },
    debug=True,
)
