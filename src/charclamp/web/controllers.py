from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

from litestar import Controller, MediaType, Request, get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Redirect, Template
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from charclamp.domain.models import BurnShift, Clamp, User, app_timezone, utcnow
from charclamp.web.time_filters import dt_input_value
from charclamp.domain.rules import (
    RuleError,
    assert_can_set_clamp_status,
    can_mark_clamp_drawn,
)
from charclamp.infra.db import SessionLocal
from charclamp.infra.security import verify_password

# 表单钟面（datetime-local 为朴素墙钟）统一按窑场时区解释，再归一化为带时区时刻。
SHIFT_TZ = app_timezone()

STATUS_LABELS = {
    Clamp.STATUS_STACKED: "已码窑",
    Clamp.STATUS_BURNING: "焖烧中",
    Clamp.STATUS_DRAWN: "已出炭",
}


def _set_flash(request: Request, message: str, category: str = "ok") -> None:
    data = dict(request.session or {})
    data["flash"] = message
    data["flash_cat"] = category
    request.set_session(data)


def _pop_flash(request: Request) -> tuple[str | None, str | None]:
    data = dict(request.session or {})
    message = data.pop("flash", None)
    category = data.pop("flash_cat", None)
    if message is not None or category is not None:
        request.set_session(data)
    return message, category


def _parse_optional_int(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_started(raw: str | None) -> datetime:
    """解析开始时刻：朴素墙钟按窑场时区解释，返回带时区（UTC 归一）的 datetime。"""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("开始时间必填")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("开始时间格式无效") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHIFT_TZ)
    return parsed.astimezone(timezone.utc)


def _parse_peak(raw: str | None) -> float:
    raw = (raw or "").strip()
    if raw == "":
        raise ValueError("峰值温度必填")
    try:
        peak = float(raw)
    except ValueError as exc:
        raise ValueError("峰值温度须为数字") from exc
    if not isfinite(peak) or peak <= 0:
        raise ValueError("峰值温度须为正数")
    return peak


async def _load_timeline_context(clamp_id: int | None = None) -> dict[str, Any]:
    async with SessionLocal() as db:
        clamps = list(
            (
                await db.execute(
                    select(Clamp)
                    .options(selectinload(Clamp.site), selectinload(Clamp.shifts))
                    .order_by(Clamp.code)
                )
            )
            .scalars()
            .all()
        )
        query = (
            select(BurnShift)
            .options(selectinload(BurnShift.clamp).selectinload(Clamp.site))
            .order_by(BurnShift.started_at.desc(), BurnShift.id.desc())
        )
        if clamp_id is not None:
            query = query.where(BurnShift.clamp_id == clamp_id)
        shifts = list((await db.execute(query)).scalars().all())
        site_name = clamps[0].site.name if clamps else "乌石岗焖烧坞"
    return {
        "clamps": clamps,
        "shifts": shifts,
        "active_clamp_id": clamp_id,
        "status_labels": STATUS_LABELS,
        "site_name": site_name,
    }


class AuthController(Controller):
    path = ""
    tags = ["auth"]

    @get("/login", media_type=MediaType.HTML)
    async def login_page(self, request: Request) -> Template:
        flash, flash_cat = _pop_flash(request)
        return Template(
            template_name="login.html",
            context={"flash": flash, "flash_cat": flash_cat},
        )

    @post("/login")
    async def login(
        self,
        request: Request,
        data: dict[str, Any] = Body(media_type=RequestEncodingType.URL_ENCODED),
    ) -> Redirect:
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        async with SessionLocal() as db:
            result = await db.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
            if not user or not verify_password(password, user.password_hash):
                request.set_session({"flash": "用户名或密码错误", "flash_cat": "error"})
                return Redirect("/login")
            request.set_session({"user_id": user.id})
        return Redirect("/")

    @get("/logout")
    async def logout(self, request: Request) -> Redirect:
        request.clear_session()
        return Redirect("/login")


class TimelineController(Controller):
    path = ""
    tags = ["timeline"]

    @get("/", media_type=MediaType.HTML)
    async def timeline(self, request: Request) -> Template | Redirect:
        if not request.user:
            return Redirect("/login")
        flash, flash_cat = _pop_flash(request)
        clamp_id = _parse_optional_int(request.query_params.get("clamp_id"))
        ctx = await _load_timeline_context(clamp_id)
        return Template(
            template_name="timeline.html",
            context={
                **ctx,
                "user": request.user,
                "flash": flash,
                "flash_cat": flash_cat,
            },
        )

    @get("/timeline/partial", media_type=MediaType.HTML)
    async def timeline_partial(self, request: Request) -> Template | Redirect:
        if not request.user:
            return Redirect("/login")
        clamp_id = _parse_optional_int(request.query_params.get("clamp_id"))
        ctx = await _load_timeline_context(clamp_id)
        return Template(
            template_name="partials/board.html",
            context={
                **ctx,
                "user": request.user,
            },
        )

    async def _shift_drawer(
        self, request: Request, clamps: list[Clamp], shift: BurnShift | None, preselect: int | None
    ) -> Template:
        return Template(
            template_name="partials/drawer_shift.html",
            context={
                "clamps": clamps,
                "shift": shift,
                "preselect_clamp_id": preselect,
                "now_local_value": dt_input_value(utcnow()),
                "user": request.user,
            },
        )

    @get("/drawer/shift-new", media_type=MediaType.HTML)
    async def drawer_shift_new(self, request: Request) -> Template | Redirect:
        if not request.user:
            return Redirect("/login")
        clamp_id = _parse_optional_int(request.query_params.get("clamp_id"))
        async with SessionLocal() as db:
            clamps = list((await db.execute(select(Clamp).order_by(Clamp.code))).scalars().all())
        return await self._shift_drawer(request, clamps, None, clamp_id)

    @get("/drawer/shift-edit/{shift_id:int}", media_type=MediaType.HTML)
    async def drawer_shift_edit(self, request: Request, shift_id: int) -> Template | Redirect:
        if not request.user:
            return Redirect("/login")
        async with SessionLocal() as db:
            shift = (
                await db.execute(
                    select(BurnShift)
                    .where(BurnShift.id == shift_id)
                    .options(selectinload(BurnShift.clamp))
                )
            ).scalar_one_or_none()
            if shift is None:
                return Redirect("/")
            clamps = list((await db.execute(select(Clamp).order_by(Clamp.code))).scalars().all())
            preselect = shift.clamp_id
        return await self._shift_drawer(request, clamps, shift, preselect)

    @get("/drawer/clamp/{clamp_id:int}", media_type=MediaType.HTML)
    async def drawer_clamp(self, request: Request, clamp_id: int) -> Template | Redirect:
        if not request.user:
            return Redirect("/login")
        async with SessionLocal() as db:
            result = await db.execute(
                select(Clamp)
                .where(Clamp.id == clamp_id)
                .options(selectinload(Clamp.shifts), selectinload(Clamp.site))
            )
            clamp = result.scalar_one_or_none()
            if not clamp:
                return Redirect("/")
        can_drawn, drawn_msg = can_mark_clamp_drawn(clamp)
        return Template(
            template_name="partials/drawer_clamp.html",
            context={
                "clamp": clamp,
                "status_labels": STATUS_LABELS,
                "can_drawn": can_drawn,
                "drawn_msg": drawn_msg,
                "user": request.user,
            },
        )


class ShiftController(Controller):
    path = "/shifts"
    tags = ["shifts"]

    @post("/save")
    async def save_shift(
        self,
        request: Request,
        data: dict[str, Any] = Body(media_type=RequestEncodingType.URL_ENCODED),
    ) -> Redirect:
        if not request.user:
            return Redirect("/login")

        clamp_id = _parse_optional_int((data.get("clamp_id") or "").strip())
        if clamp_id is None:
            _set_flash(request, "登记失败：未选择炭窑", "error")
            return Redirect("/")
        shift_id = _parse_optional_int(data.get("shift_id"))

        # 全部输入校验在开事务之前完成：非法请求不产生任何 INSERT。
        try:
            started_at = _parse_started(data.get("started_at"))
            peak_temp = _parse_peak(data.get("peak_temp_c"))
        except ValueError as exc:
            _set_flash(request, f"登记失败：{exc}", "error")
            return Redirect(f"/?clamp_id={clamp_id}")

        charcoal_grade = (data.get("charcoal_grade") or "B").strip() or "B"
        notes = (data.get("notes") or "").strip()

        async with SessionLocal() as db:
            try:
                # 单事务：新建/覆盖 + 窑态翻转同生共死，任何失败整体回滚。
                async with db.begin():
                    clamp = (
                        await db.execute(
                            select(Clamp).where(Clamp.id == clamp_id).with_for_update()
                        )
                    ).scalar_one_or_none()
                    if clamp is None:
                        raise RuleError("炭窑不存在")

                    if shift_id is not None:
                        shift = (
                            await db.execute(
                                select(BurnShift)
                                .where(BurnShift.id == shift_id)
                                .with_for_update()
                            )
                        ).scalar_one_or_none()
                        if shift is None:
                            raise RuleError("班次不存在，无法改写")
                    else:
                        shift = BurnShift(clamp_id=clamp_id)
                        db.add(shift)
                        await db.flush()

                    # 新建与改写走同一套覆盖写入，字段全量落库。
                    shift.clamp_id = clamp_id
                    shift.started_at = started_at
                    shift.peak_temp_c = peak_temp
                    shift.charcoal_grade = charcoal_grade
                    shift.notes = notes
                    if clamp.status == Clamp.STATUS_STACKED:
                        clamp.status = Clamp.STATUS_BURNING
            except RuleError as exc:
                _set_flash(request, f"登记失败：{exc}", "error")
                return Redirect(f"/?clamp_id={clamp_id}")

        _set_flash(request, "焖烧班次已登记" if shift_id is None else "焖烧班次已改写", "ok")
        return Redirect(f"/?clamp_id={clamp_id}")


class ClampController(Controller):
    path = "/clamps"
    tags = ["clamps"]

    @post("/{clamp_id:int}/status")
    async def set_status(
        self,
        request: Request,
        clamp_id: int,
        data: dict[str, Any] = Body(media_type=RequestEncodingType.URL_ENCODED),
    ) -> Redirect:
        if not request.user:
            return Redirect("/login")
        new_status = (data.get("status") or "").strip()
        async with SessionLocal() as db:
            result = await db.execute(
                select(Clamp)
                .where(Clamp.id == clamp_id)
                .options(selectinload(Clamp.shifts))
            )
            clamp = result.scalar_one_or_none()
            if not clamp:
                return Redirect("/")
            try:
                assert_can_set_clamp_status(clamp, new_status)
                clamp.status = new_status
                await db.commit()
                _set_flash(request, f"窑 {clamp.code} 状态已更新", "ok")
            except RuleError as exc:
                _set_flash(request, str(exc), "error")
        return Redirect(f"/?clamp_id={clamp_id}")
