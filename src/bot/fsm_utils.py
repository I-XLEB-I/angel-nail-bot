from __future__ import annotations

from aiogram.fsm.context import FSMContext

from src.bot.admin_panel import clear_state_preserving_admin_panel


async def clear_state_preserving_admin_mode(state: FSMContext) -> None:
    """Clear FSM state while keeping admin-mode routing and panel references."""
    admin_as_client = (await state.get_data()).get("admin_as_client", False)
    await clear_state_preserving_admin_panel(
        state,
        admin_as_client=bool(admin_as_client),
    )
