"""Named warehouse group definitions.

Add new groups here — the agent and cross-warehouse stock tool use these
to resolve group names (e.g. 'CASA') to a list of EWM warehouse codes.
"""
from __future__ import annotations

WAREHOUSE_GROUPS: dict[str, list[str]] = {
    "CASA": ["PBAR", "POR2", "PWOO", "PFEN", "PLA3", "WFEN"],
}


def resolve_group(name: str) -> list[str] | None:
    """Return warehouse list for a group name (case-insensitive). None if not found."""
    return WAREHOUSE_GROUPS.get(name.upper())


def list_groups() -> str:
    lines = ["Defined warehouse groups:\n"]
    for grp, whs in WAREHOUSE_GROUPS.items():
        lines.append(f"  {grp}: {', '.join(whs)}")
    return "\n".join(lines)
