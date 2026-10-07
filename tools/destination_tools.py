"""Destination switching tools — let users connect to a different BTP destination at runtime."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import _DestinationResolver

logger = logging.getLogger(__name__)


class SwitchDestinationInput(BaseModel):
    destination_name: str = Field(description="BTP destination name to switch to, e.g. 'S4X-100', 'S4D-200'")


class GetDestinationInput(BaseModel):
    pass


def make_switch_destination(
    resolver: "_DestinationResolver",
    registry: dict[str, str],
    context_id: str,
    default_dest: str,
) -> StructuredTool:
    async def switch_destination(destination_name: str) -> str:
        try:
            dest = await resolver.resolve(destination_name)
            registry[context_id] = destination_name
            logger.info("context=%s switched destination to %s (url=%s)", context_id, destination_name, dest.url)
            return (
                f"✅ Switched to destination **{destination_name}** "
                f"(URL: `{dest.url}`, proxy: {dest.proxy_type}). "
                f"All subsequent queries will use this system."
            )
        except Exception as e:
            return f"❌ Could not switch to destination '{destination_name}': {e}"

    return StructuredTool.from_function(
        coroutine=switch_destination,
        name="switch_destination",
        description=(
            "Switch the active SAP S/4HANA destination for this session. "
            "Use when the user asks to connect to a different system or destination, "
            "e.g. 'switch to S4D-200', 'use destination S4X-100', 'connect to the dev system'. "
            "The destination must exist in BTP and be accessible via the bound destination service."
        ),
        args_schema=SwitchDestinationInput,
    )


def make_get_active_destination(
    registry: dict[str, str],
    context_id: str,
    default_dest: str,
) -> StructuredTool:
    def get_active_destination() -> str:
        active = registry.get(context_id, default_dest)
        is_default = active == default_dest
        return (
            f"Active destination: **{active}**"
            + (" (default)" if is_default else " (user-selected)")
        )

    return StructuredTool.from_function(
        func=get_active_destination,
        name="get_active_destination",
        description="Returns the currently active SAP destination for this session.",
        args_schema=GetDestinationInput,
    )
