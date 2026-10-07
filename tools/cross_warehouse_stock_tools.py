"""Cross-Warehouse Stock tool — queries stock across all EWM warehouses.

Uses API_WHSE_PHYSSTOCKPROD (OData V4) without a warehouse filter to get
stock totals across all warehouses in one call. Supports named warehouse groups
defined in warehouse_groups.py (e.g. group='CASA').
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from s4hana_client import Client

from warehouse_groups import resolve_group, list_groups

logger = logging.getLogger(__name__)

_PHYS_SRV = "/sap/opu/odata4/sap/api_whse_physstockprod/srvd_a2x/sap/api_whse_physstockprod/0001"
MAX_PAGE_SIZE = 500

STOCK_TYPE_LABELS = {
    "F1": "Unrestricted", "F2": "Unrestricted",
    "S1": "Blocked",      "S2": "Blocked",
    "Q1": "Quality",      "Q2": "Quality",
    "R1": "Returns",      "T1": "In Transfer",
    "W1": "Work in Process",
    "F":  "Unrestricted", "S": "Blocked",
    "Q":  "Quality",      "T": "In Transfer",
}


def _results(payload: Any) -> tuple[list[dict], str]:
    if isinstance(payload, dict):
        err = payload.get("error")
        if err:
            if isinstance(err, dict):
                msg = err.get("message", {})
                text = msg.get("value", str(err)) if isinstance(msg, dict) else str(msg)
                return [], f"SAP error [{err.get('code','')}]: {text}"
            return [], f"SAP error: {err}"
        v = payload.get("value", [])
        return (v if isinstance(v, list) else []), ""
    if isinstance(payload, list):
        return payload, ""
    return [], ""


class GetCrossWarehouseStockInput(BaseModel):
    group: str = Field(
        default="",
        description="Named warehouse group (e.g. 'CASA'). Takes precedence over warehouses param. Use 'LIST' to see all groups.",
    )
    product: str = Field(
        default="",
        description="Product/material number to look up across all warehouses (optional but recommended)",
    )
    warehouses: str = Field(
        default="",
        description="Comma-separated list of EWM warehouse codes to include (e.g. 'PBAR,MSTR'). Leave blank for all warehouses.",
    )
    stock_type: str = Field(
        default="",
        description="Stock type filter: F=Unrestricted, Q=Quality, S=Blocked, T=InTransfer. Leave blank for all.",
    )
    group_by_warehouse: bool = Field(
        default=True,
        description="If true (default), show totals grouped by warehouse then product. If false, show individual stock lines.",
    )
    top: int = Field(default=200, description="Max stock records to fetch (max 500)")


def make_get_cross_warehouse_stock(s4: "Client", user_id: str | None = None) -> StructuredTool:
    async def get_cross_warehouse_stock(
        group: str = "",
        product: str = "",
        warehouses: str = "",
        stock_type: str = "",
        group_by_warehouse: bool = True,
        top: int = 200,
    ) -> str:
        # ── Group resolution ─────────────────────────────────────────────────
        if group:
            if group.upper() == "LIST":
                return list_groups()
            resolved = resolve_group(group)
            if resolved is None:
                return f"Unknown warehouse group '{group}'.\n\n{list_groups()}"
            wh_list = resolved
            scope_label = f"Group: {group.upper()} ({', '.join(wh_list)})"
        else:
            wh_list = [w.strip() for w in warehouses.split(",") if w.strip()] if warehouses else []
            scope_label = f"Warehouses: {', '.join(wh_list)}" if wh_list else "All Warehouses"

        capped = min(top, MAX_PAGE_SIZE)
        filters: list[str] = []

        if product:
            filters.append(f"Product eq '{product}'")

        if len(wh_list) == 1:
            filters.append(f"EWMWarehouse eq '{wh_list[0]}'")
        elif len(wh_list) > 1:
            wh_or = " or ".join(f"EWMWarehouse eq '{w}'" for w in wh_list)
            filters.append(f"({wh_or})")

        if stock_type:
            st = stock_type.upper().strip()
            if len(st) == 1:
                # F → matches F1, F2; Q → Q1, Q2; etc.
                filters.append(f"startswith(EWMStockType,'{st}') eq true")
            else:
                filters.append(f"EWMStockType eq '{st}'")

        params: dict[str, Any] = {
            "$format": "json",
            "$top": str(capped),
            "$select": (
                "EWMWarehouse,Product,EWMStockType,EWMStorageType,"
                "EWMStockQuantityInBaseUnit,EWMStockQuantityBaseUnit"
            ),
            "$orderby": "EWMWarehouse,Product",
        }
        if filters:
            params["$filter"] = " and ".join(filters)

        result = await s4.get_v4(
            f"{_PHYS_SRV}/WarehousePhysicalStockProducts",
            params=params,
            user_identity=user_id,
        )
        rows, err = _results(result)
        if err:
            return err
        if not rows:
            desc = product or "all products"
            return f"No stock found for {desc} — {scope_label}."

        # ── Group-by summary mode ────────────────────────────────────────────
        if group_by_warehouse:
            # Aggregate: warehouse → product → stock_type → total qty
            totals: dict[str, dict[str, dict[str, float]]] = defaultdict(
                lambda: defaultdict(lambda: defaultdict(float))
            )
            units: dict[str, str] = {}
            for r in rows:
                wh = r.get("EWMWarehouse", "")
                prod = r.get("Product", "")
                stype = r.get("EWMStockType", "")
                try:
                    qty = float(r.get("EWMStockQuantityInBaseUnit") or 0)
                except (ValueError, TypeError):
                    qty = 0.0
                totals[wh][prod][stype] += qty
                if prod not in units:
                    units[prod] = r.get("EWMStockQuantityBaseUnit", "")

            # Find warehouses with stock
            active_whs = sorted(totals.keys())
            wh_products: set[str] = set()
            for wh in active_whs:
                wh_products.update(totals[wh].keys())

            lines = [
                f"Cross-Warehouse Stock Summary — {scope_label}",
                f"({len(rows)} stock lines, {len(active_whs)} warehouse(s))",
                "",
            ]

            if product:
                # Single product: one row per warehouse
                lines.append(f"Product: {product}")
                lines.append("")
                col_w = max(len(w) for w in active_whs) if active_whs else 10
                lines.append(f"{'Warehouse':{col_w}}  {'Unrestricted':>14}  {'Quality':>10}  {'Blocked':>10}  {'InTransfer':>11}  {'Unit'}")
                lines.append("-" * (col_w + 55))
                grand_unres = grand_qi = grand_blk = grand_tr = 0.0
                unit = units.get(product, "")
                for wh in active_whs:
                    wh_data = totals[wh].get(product, {})
                    unres = sum(v for k, v in wh_data.items() if k.startswith("F"))
                    qi    = sum(v for k, v in wh_data.items() if k.startswith("Q"))
                    blk   = sum(v for k, v in wh_data.items() if k.startswith("S"))
                    tr    = sum(v for k, v in wh_data.items() if k.startswith("T"))
                    total = unres + qi + blk + tr
                    if total == 0:
                        continue
                    grand_unres += unres; grand_qi += qi; grand_blk += blk; grand_tr += tr
                    lines.append(
                        f"{wh:{col_w}}  {unres:>14.3f}  {qi:>10.3f}  {blk:>10.3f}  {tr:>11.3f}  {unit}"
                    )
                lines.append("-" * (col_w + 55))
                lines.append(
                    f"{'TOTAL':{col_w}}  {grand_unres:>14.3f}  {grand_qi:>10.3f}  {grand_blk:>10.3f}  {grand_tr:>11.3f}  {unit}"
                )
            else:
                # All products: group by warehouse → product rows
                for wh in active_whs:
                    wh_total = 0.0
                    wh_lines = []
                    for prod in sorted(totals[wh].keys()):
                        wh_data = totals[wh][prod]
                        unres = sum(v for k, v in wh_data.items() if k.startswith("F"))
                        qi    = sum(v for k, v in wh_data.items() if k.startswith("Q"))
                        blk   = sum(v for k, v in wh_data.items() if k.startswith("S"))
                        tr    = sum(v for k, v in wh_data.items() if k.startswith("T"))
                        total = unres + qi + blk + tr
                        wh_total += total
                        unit = units.get(prod, "")
                        parts = []
                        if unres: parts.append(f"Unres:{unres:.3f}")
                        if qi:    parts.append(f"QI:{qi:.3f}")
                        if blk:   parts.append(f"Blk:{blk:.3f}")
                        if tr:    parts.append(f"Tr:{tr:.3f}")
                        wh_lines.append(f"    {prod:25} {' | '.join(parts)} {unit}")
                    lines.append(f"Warehouse {wh}  (total lines: {len(totals[wh])}, total qty: {wh_total:.0f}):")
                    lines.extend(wh_lines)
                    lines.append("")

        else:
            # ── Flat detail mode ─────────────────────────────────────────────
            header = (
                f"Cross-Warehouse Stock Detail — {scope_label} ({len(rows)} lines):\n\n"
                "| Warehouse | Product                   | StorType | StockType    | Qty          | Unit |\n"
                "|-----------|---------------------------|----------|--------------|--------------|------|\n"
            )
            detail_lines = []
            for r in rows:
                stype = r.get("EWMStockType", "")
                label = STOCK_TYPE_LABELS.get(stype, stype)
                try:
                    qty = float(r.get("EWMStockQuantityInBaseUnit") or 0)
                except (ValueError, TypeError):
                    qty = 0.0
                detail_lines.append(
                    f"| {r.get('EWMWarehouse',''):9} "
                    f"| {r.get('Product',''):25} "
                    f"| {r.get('EWMStorageType','') or '-':8} "
                    f"| {label:12} "
                    f"| {qty:>12.3f} "
                    f"| {r.get('EWMStockQuantityBaseUnit',''):4} |"
                )
            return header + "\n".join(detail_lines)

        return "\n".join(lines)

    return StructuredTool(
        name="get_cross_warehouse_stock",
        description=(
            "Query EWM physical stock across ALL warehouses or a named warehouse group. "
            "Use group='CASA' to query only CASA warehouses (PBAR, POR2, PWOO, PFEN, PLA3, WFEN). "
            "Use group='LIST' to see all defined warehouse groups. "
            "Use product to find where a specific material is stocked. "
            "Use warehouses='PBAR,MSTR' to limit to specific warehouses. "
            "Returns tabular summary grouped by warehouse with Unrestricted/Quality/Blocked/InTransfer totals. "
            "Use group_by_warehouse=false for individual stock lines per bin/storage type."
        ),
        args_schema=GetCrossWarehouseStockInput,
        coroutine=get_cross_warehouse_stock,
    )
