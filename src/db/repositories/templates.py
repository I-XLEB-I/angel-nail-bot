from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Template
from src.services.template_sanitizer import normalize_template_content


class TemplateRepository:
    """Repository for editable templates."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_key(self, key: str) -> Template | None:
        """Return a template by key."""
        result = await self.session.execute(select(Template).where(Template.key == key))
        return result.scalar_one_or_none()

    async def get_content(self, key: str) -> str | None:
        """Return template content by key."""
        template = await self.get_by_key(key)
        return template.content if template is not None else None

    async def get_content_or_default(self, key: str, default: str) -> str:
        """Return template content or a fallback."""
        content = await self.get_content(key)
        return normalize_template_content(key, content, default)

    async def list_all(self) -> list[Template]:
        """Return all templates ordered by key."""
        result = await self.session.execute(select(Template).order_by(Template.key))
        return list(result.scalars().all())

    async def upsert(self, *, key: str, content: str) -> Template:
        """Create or update a template."""
        template = await self.get_by_key(key)
        if template is None:
            template = Template(key=key, content=content)
            self.session.add(template)
        else:
            template.content = content
        await self.session.flush()
        return template
