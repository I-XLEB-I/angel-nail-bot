from __future__ import annotations

from src.bot import texts
from src.db.repositories.templates import TemplateRepository
from src.services.admin_defaults import required_template_defaults


def render_template_text(template: str, values: dict[str, str]) -> str:
    """Replace known `{placeholders}` without failing on unknown ones."""
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


def ensure_late_policy_notice(text: str) -> str:
    """Append the standard lateness rule when the current text does not mention it."""
    stripped = text.strip()
    normalized = stripped.lower().replace("ё", "е")
    mentions_late_cancel_policy = (
        "15" in normalized
        and "отмен" in normalized
        and ("опозд" in normalized or "задерж" in normalized)
    )
    if mentions_late_cancel_policy:
        return stripped
    if not stripped:
        return texts.LATE_POLICY_CONFIRMATION_NOTICE_TEXT
    return f"{stripped}\n\n{texts.LATE_POLICY_CONFIRMATION_NOTICE_TEXT}"


async def render_named_template(
    template_repository: TemplateRepository,
    *,
    key: str,
    values: dict[str, str],
) -> str:
    """Load a template by key and render it with the provided variables."""
    defaults = required_template_defaults()
    template = await template_repository.get_content_or_default(
        key,
        defaults[key],
    )
    return render_template_text(template, values).strip()
