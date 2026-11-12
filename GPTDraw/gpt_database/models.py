"""GPTDraw 的持久化模型：密钥、会话授权、个人授权与预设。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, col
from sqlalchemy import Text, Column, UniqueConstraint, delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from gsuid_core.server import on_core_start
from gsuid_core.utils.database import base_models
from gsuid_core.webconsole.mount_app import PageSchema, GsAdminModel, site
from gsuid_core.utils.database.base_models import (
    BaseModel,
    BaseIDModel,
    BaseBotIDModel,
    with_session,
    with_read_session,
)

# 热重载时旧 admin 类还留在 site.plugins_page 里；不清会每次重载多出一套管理页。
site.plugins_page.pop("GPTDraw", None)


@on_core_start(priority=5)
async def ensure_gptdraw_tables() -> None:
    """热重载不会重跑框架的 create_all，加载后补建缺失的表。"""
    async with base_models.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


def _now() -> datetime:
    return datetime.now()


class GptKey(BaseModel, table=True):
    """用户绑定的 New API 密钥；同一用户可绑定多把，active 标记当前使用的那把。"""

    __table_args__ = (
        UniqueConstraint("bot_id", "user_id", "fingerprint", name="ux_gptdraw_key"),
        {"extend_existing": True},
    )

    fingerprint: str = Field(title="密钥指纹", max_length=64, index=True)
    api_key_cipher: str = Field(title="密钥密文", sa_column=Column(Text, nullable=False))
    hint: str = Field(title="尾号", default="", max_length=32)
    api_base: str = Field(title="绑定时的 New API 地址", default="", max_length=255)
    active: bool = Field(title="当前使用", default=True)
    created_at: datetime = Field(title="创建时间", default_factory=_now)
    updated_at: datetime = Field(title="更新时间", default_factory=_now)

    @classmethod
    @with_read_session
    async def list_keys(cls, session: AsyncSession, bot_id: str, user_id: str) -> list["GptKey"]:
        statement = (
            select(cls)
            .where(col(cls.bot_id) == bot_id)
            .where(col(cls.user_id) == user_id)
            .order_by(col(cls.active).desc(), col(cls.created_at).asc())
        )
        result = await session.execute(statement)
        return list(result.scalars().all())

    @classmethod
    @with_read_session
    async def get_active(cls, session: AsyncSession, bot_id: str, user_id: str) -> "GptKey | None":
        statement = (
            select(cls)
            .where(col(cls.bot_id) == bot_id)
            .where(col(cls.user_id) == user_id)
            .where(col(cls.active).is_(True))
            .order_by(col(cls.updated_at).desc())
        )
        result = await session.execute(statement)
        return result.scalars().first()

    @classmethod
    @with_session
    async def bind_key(
        cls,
        session: AsyncSession,
        *,
        bot_id: str,
        user_id: str,
        fingerprint: str,
        api_key_cipher: str,
        hint: str,
        api_base: str,
    ) -> bool:
        """绑定或更新一把密钥，并把它设为当前使用。"""
        await session.execute(
            update(cls).where(col(cls.bot_id) == bot_id).where(col(cls.user_id) == user_id).values(active=False)
        )
        result = await session.execute(
            select(cls)
            .where(col(cls.bot_id) == bot_id)
            .where(col(cls.user_id) == user_id)
            .where(col(cls.fingerprint) == fingerprint)
        )
        existing = result.scalars().first()
        if existing is None:
            session.add(
                cls(
                    bot_id=bot_id,
                    user_id=user_id,
                    fingerprint=fingerprint,
                    api_key_cipher=api_key_cipher,
                    hint=hint,
                    api_base=api_base,
                    active=True,
                )
            )
            return False
        existing.api_key_cipher = api_key_cipher
        existing.hint = hint
        existing.api_base = api_base
        existing.active = True
        existing.updated_at = _now()
        session.add(existing)
        return True

    @classmethod
    @with_session
    async def delete_by_index(cls, session: AsyncSession, bot_id: str, user_id: str, index: int) -> bool:
        result = await session.execute(
            select(cls)
            .where(col(cls.bot_id) == bot_id)
            .where(col(cls.user_id) == user_id)
            .order_by(col(cls.created_at).asc())
        )
        rows = list(result.scalars().all())
        if index < 0 or index >= len(rows):
            return False
        removed = rows[index]
        was_active = removed.active
        await session.delete(removed)
        await session.flush()
        if was_active:
            remaining = [row for row in rows if row.id != removed.id]
            if remaining:
                remaining[-1].active = True
                remaining[-1].updated_at = _now()
                session.add(remaining[-1])
        return True

    @classmethod
    @with_session
    async def delete_all_for_user(cls, session: AsyncSession, bot_id: str, user_id: str) -> int:
        result = await session.execute(delete(cls).where(col(cls.bot_id) == bot_id).where(col(cls.user_id) == user_id))
        return result.rowcount if isinstance(result, CursorResult) else 0

    @classmethod
    @with_read_session
    async def list_all_by_bot(cls, session: AsyncSession, bot_id: str) -> list["GptKey"]:
        result = await session.execute(
            select(cls).where(col(cls.bot_id) == bot_id).order_by(col(cls.user_id), col(cls.created_at))
        )
        return list(result.scalars().all())


class GptSessionAuth(BaseBotIDModel, table=True):
    """会话级授权：某个群整体使用某人的密钥生图。"""

    __table_args__ = (
        UniqueConstraint("bot_id", "scope_id", name="ux_gptdraw_session"),
        {"extend_existing": True},
    )

    scope_id: str = Field(title="会话作用域", max_length=120, index=True)
    owner_user_id: str = Field(title="授权人", max_length=64)
    enabled: bool = Field(title="已开启", default=False)
    created_at: datetime = Field(title="创建时间", default_factory=_now)
    updated_at: datetime = Field(title="更新时间", default_factory=_now)

    @classmethod
    @with_read_session
    async def get_auth(cls, session: AsyncSession, bot_id: str, scope_id: str) -> "GptSessionAuth | None":
        result = await session.execute(
            select(cls).where(col(cls.bot_id) == bot_id).where(col(cls.scope_id) == scope_id)
        )
        return result.scalars().first()

    @classmethod
    @with_session
    async def set_auth(
        cls,
        session: AsyncSession,
        *,
        bot_id: str,
        scope_id: str,
        owner_user_id: str,
        enabled: bool,
    ) -> "GptSessionAuth":
        result = await session.execute(
            select(cls).where(col(cls.bot_id) == bot_id).where(col(cls.scope_id) == scope_id)
        )
        row = result.scalars().first()
        if row is None:
            row = cls(bot_id=bot_id, scope_id=scope_id, owner_user_id=owner_user_id, enabled=enabled)
        else:
            row.owner_user_id = owner_user_id
            row.enabled = enabled
            row.updated_at = _now()
        session.add(row)
        await session.flush()
        return row

    @classmethod
    @with_session
    async def clear_owner(cls, session: AsyncSession, bot_id: str, owner_user_id: str) -> int:
        result = await session.execute(
            update(cls)
            .where(col(cls.bot_id) == bot_id)
            .where(col(cls.owner_user_id) == owner_user_id)
            .values(enabled=False, updated_at=_now())
        )
        return result.rowcount if isinstance(result, CursorResult) else 0


class GptGrant(BaseBotIDModel, table=True):
    """个人授权：绑定者在群里授权某个用户私聊使用自己的密钥。"""

    __table_args__ = (
        UniqueConstraint("bot_id", "target_user_id", name="ux_gptdraw_grant"),
        {"extend_existing": True},
    )

    owner_user_id: str = Field(title="授权人", max_length=64, index=True)
    target_user_id: str = Field(title="被授权人", max_length=64, index=True)
    created_at: datetime = Field(title="创建时间", default_factory=_now)

    @classmethod
    @with_read_session
    async def get_owner_for_target(cls, session: AsyncSession, bot_id: str, target_user_id: str) -> "GptGrant | None":
        result = await session.execute(
            select(cls).where(col(cls.bot_id) == bot_id).where(col(cls.target_user_id) == target_user_id)
        )
        return result.scalars().first()

    @classmethod
    @with_session
    async def add_grant(cls, session: AsyncSession, *, bot_id: str, owner_user_id: str, target_user_id: str) -> bool:
        result = await session.execute(
            select(cls).where(col(cls.bot_id) == bot_id).where(col(cls.target_user_id) == target_user_id)
        )
        row = result.scalars().first()
        if row is not None and row.owner_user_id == owner_user_id:
            return False
        if row is None:
            row = cls(bot_id=bot_id, owner_user_id=owner_user_id, target_user_id=target_user_id)
        else:
            row.owner_user_id = owner_user_id
        session.add(row)
        await session.flush()
        return True

    @classmethod
    @with_session
    async def remove_grant(cls, session: AsyncSession, *, bot_id: str, owner_user_id: str, target_user_id: str) -> bool:
        result = await session.execute(
            delete(cls)
            .where(col(cls.bot_id) == bot_id)
            .where(col(cls.owner_user_id) == owner_user_id)
            .where(col(cls.target_user_id) == target_user_id)
        )
        return (result.rowcount if isinstance(result, CursorResult) else 0) > 0

    @classmethod
    @with_read_session
    async def list_by_owner(cls, session: AsyncSession, bot_id: str, owner_user_id: str) -> list["GptGrant"]:
        result = await session.execute(
            select(cls)
            .where(col(cls.bot_id) == bot_id)
            .where(col(cls.owner_user_id) == owner_user_id)
            .order_by(col(cls.created_at).asc())
        )
        return list(result.scalars().all())

    @classmethod
    @with_session
    async def delete_for_owner(cls, session: AsyncSession, bot_id: str, owner_user_id: str) -> int:
        result = await session.execute(
            delete(cls).where(col(cls.bot_id) == bot_id).where(col(cls.owner_user_id) == owner_user_id)
        )
        return result.rowcount if isinstance(result, CursorResult) else 0


class GptPreset(BaseIDModel, table=True):
    """本地自定义生图预设。远程提示词库只缓存在内存，不写入本表。"""

    __table_args__ = (
        UniqueConstraint("name_key", name="ux_gptdraw_preset"),
        {"extend_existing": True},
    )

    name: str = Field(title="预设名", max_length=32)
    name_key: str = Field(title="预设名归一", max_length=32, index=True)
    prompt: str = Field(title="提示词", sa_column=Column(Text, nullable=False))
    reply: str = Field(title="出图提示语", default="", max_length=255)
    image: str = Field(title="预览图", default="", max_length=255)
    created_by: str = Field(title="创建者", default="", max_length=64)
    created_at: datetime = Field(title="创建时间", default_factory=_now)
    updated_at: datetime = Field(title="更新时间", default_factory=_now)

    @classmethod
    @with_read_session
    async def get_by_name(cls, session: AsyncSession, name_key: str) -> "GptPreset | None":
        result = await session.execute(select(cls).where(col(cls.name_key) == name_key))
        return result.scalars().first()

    @classmethod
    @with_read_session
    async def list_all(cls, session: AsyncSession) -> list["GptPreset"]:
        result = await session.execute(select(cls).order_by(col(cls.name)))
        return list(result.scalars().all())

    @classmethod
    @with_session
    async def upsert_preset(
        cls,
        session: AsyncSession,
        *,
        name: str,
        name_key: str,
        prompt: str,
        created_by: str,
        reply: str = "",
        image: str = "",
    ) -> None:
        result = await session.execute(select(cls).where(col(cls.name_key) == name_key))
        row = result.scalars().first()
        if row is None:
            row = cls(name=name, name_key=name_key, prompt=prompt, reply=reply, image=image, created_by=created_by)
        else:
            row.name = name
            row.prompt = prompt
            row.reply = reply
            row.image = image
            row.updated_at = _now()
        session.add(row)

    @classmethod
    @with_session
    async def delete_by_name(cls, session: AsyncSession, name_key: str) -> bool:
        result = await session.execute(delete(cls).where(col(cls.name_key) == name_key))
        return (result.rowcount if isinstance(result, CursorResult) else 0) > 0


class GptModelChoice(BaseModel, table=True):
    """每个用户当前选中的生图模型；没有记录时用配置里的默认模型。"""

    __table_args__ = (
        UniqueConstraint("bot_id", "user_id", name="ux_gptdraw_model"),
        {"extend_existing": True},
    )

    model: str = Field(title="当前模型", max_length=120)
    updated_at: datetime = Field(title="更新时间", default_factory=_now)

    @classmethod
    @with_read_session
    async def get_choice(cls, session: AsyncSession, bot_id: str, user_id: str) -> "GptModelChoice | None":
        result = await session.execute(select(cls).where(col(cls.bot_id) == bot_id).where(col(cls.user_id) == user_id))
        return result.scalars().first()

    @classmethod
    @with_session
    async def set_choice(cls, session: AsyncSession, bot_id: str, user_id: str, model: str) -> None:
        result = await session.execute(select(cls).where(col(cls.bot_id) == bot_id).where(col(cls.user_id) == user_id))
        row = result.scalars().first()
        if row is None:
            row = cls(bot_id=bot_id, user_id=user_id, model=model)
        else:
            row.model = model
            row.updated_at = _now()
        session.add(row)

    @classmethod
    @with_session
    async def clear_choice(cls, session: AsyncSession, bot_id: str, user_id: str) -> bool:
        result = await session.execute(delete(cls).where(col(cls.bot_id) == bot_id).where(col(cls.user_id) == user_id))
        return (result.rowcount if isinstance(result, CursorResult) else 0) > 0


@site.register_admin
class GptKeyAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(label="GPTDraw 密钥管理", icon="fa fa-key")
    model = GptKey


@site.register_admin
class GptPresetAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(label="GPTDraw 预设管理", icon="fa fa-magic")
    model = GptPreset


@site.register_admin
class GptSessionAuthAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(label="GPTDraw 会话授权", icon="fa fa-users")
    model = GptSessionAuth


@site.register_admin
class GptGrantAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(label="GPTDraw 个人授权", icon="fa fa-user-plus")
    model = GptGrant


@site.register_admin
class GptModelChoiceAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(label="GPTDraw 模型选择", icon="fa fa-microchip")
    model = GptModelChoice


__all__ = [
    "GptGrant",
    "GptKey",
    "GptModelChoice",
    "GptPreset",
    "GptSessionAuth",
]
