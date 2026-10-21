"""Warehouse agent domain tool registry."""
from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from s4hana_client import Client

from tools.production_order_tools import (
    make_get_production_order,
    make_get_production_order_components,
    make_get_production_order_operations,
    make_get_production_confirmations,
)
from tools.production_order_odata_tools import (
    make_get_production_orders_odata,
    make_get_production_order_status_odata,
    make_get_production_order_components_odata,
    make_get_production_order_operations_odata,
)
from tools.production_execution_tools import (
    make_post_goods_issue_production,
    make_post_production_confirmation,
    make_post_goods_receipt_production,
)
from tools.ewm_warehouse_tools import (
    make_get_warehouses,
    make_get_storage_types,
)
from tools.ewm_resource_tools import (
    make_get_warehouse_resources,
    make_get_resource_group_queues,
)
from tools.stock_tools import make_get_material_stock, make_get_stock_overview
from tools.inbound_delivery_tools import (
    make_get_inbound_deliveries,
    make_get_inbound_delivery_detail,
    make_get_delivery_items,
    make_get_delivery_doc_flow,
)
from tools.goods_movement_tools import (
    make_get_material_documents,
    make_post_goods_receipt,
    make_create_sto,
    make_post_sto_goods_issue,
    make_post_sto_goods_receipt_no_del,
    make_execute_sto_transfer,
)
from tools.warehouse_order_tools import (
    make_get_warehouse_orders,
    make_get_warehouse_tasks,
    make_get_warehouse_task_detail,
)
from tools.ewm_stock_tools import (
    make_get_ewm_available_stock,
    make_get_ewm_physical_stock,
)
from tools.cross_warehouse_stock_tools import make_get_cross_warehouse_stock
from tools.purchase_order_tools import (
    make_get_purchase_orders,
    make_get_po_details,
)
from tools.warehouse_task_confirm_tools import (
    make_confirm_warehouse_task,
    make_confirm_warehouse_task_exact,
)
from tools.ewm_outbound_tools import (
    make_get_ewm_outbound_deliveries,
    make_get_ewm_outbound_delivery_items,
)
from tools.storage_bin_tools import (
    make_get_storage_bins,
    make_get_fixed_bin_assignments,
)
from tools.ewm_physical_inventory_tools import (
    make_get_phys_inventory_docs,
    make_get_phys_inventory_count_items,
)
from tools.ewm_inbound_gr_tools import (
    make_list_ewm_inbound_deliveries,
    make_get_ewm_inbound_delivery,
    make_post_ewm_inbound_gr,
)
from tools.batch_tools import (
    make_search_batches,
    make_get_batch_classification,
)


def build_domain_tools(
    s4: "Client",
    user_id: str | None = None,
) -> Sequence[BaseTool]:
    """Build all warehouse domain tools wired to the given S4HANA client. (48 tools)"""
    return [
        # MM Stock (OData V2)
        make_get_material_stock(s4, user_id),
        make_get_stock_overview(s4, user_id),
        # Inbound Delivery (OData V2)
        make_get_inbound_deliveries(s4, user_id),
        make_get_inbound_delivery_detail(s4, user_id),
        make_get_delivery_items(s4, user_id),
        make_get_delivery_doc_flow(s4, user_id),
        # Goods Movements (OData V2)
        make_get_material_documents(s4, user_id),
        make_post_goods_receipt(s4, user_id),
        # STO Transfer without delivery (V4 create + V2 GI/GR)
        make_create_sto(s4, user_id),
        make_post_sto_goods_issue(s4, user_id),
        make_post_sto_goods_receipt_no_del(s4, user_id),
        make_execute_sto_transfer(s4, user_id),
        # EWM Warehouse Order & Task (OData V4)
        make_get_warehouse_orders(s4, user_id),
        make_get_warehouse_tasks(s4, user_id),
        make_get_warehouse_task_detail(s4, user_id),
        # EWM Stock (OData V4)
        make_get_ewm_available_stock(s4, user_id),
        make_get_ewm_physical_stock(s4, user_id),
        make_get_cross_warehouse_stock(s4, user_id),
        # EWM Task Confirmation (OData V4 action)
        make_confirm_warehouse_task(s4, user_id),
        make_confirm_warehouse_task_exact(s4, user_id),
        # EWM Outbound Delivery (OData V4)
        make_get_ewm_outbound_deliveries(s4, user_id),
        make_get_ewm_outbound_delivery_items(s4, user_id),
        # Storage Bin Master (OData V4)
        make_get_storage_bins(s4, user_id),
        make_get_fixed_bin_assignments(s4, user_id),
        # EWM Physical Inventory (OData V4)
        make_get_phys_inventory_docs(s4, user_id),
        make_get_phys_inventory_count_items(s4, user_id),
        # EWM Inbound Delivery Goods Receipt (A2X OData V4 — API_WAREHOUSE_INBOUNDDELIVERY)
        make_list_ewm_inbound_deliveries(s4, user_id),
        make_get_ewm_inbound_delivery(s4, user_id),
        make_post_ewm_inbound_gr(s4, user_id),
        # EWM Warehouse Master (OData V4)
        make_get_warehouses(s4, user_id),
        make_get_storage_types(s4, user_id),
        # EWM Warehouse Resources (OData V4)
        make_get_warehouse_resources(s4, user_id),
        make_get_resource_group_queues(s4, user_id),
        # Production Order — read BAPI/SOAP
        make_get_production_order(s4, user_id),
        make_get_production_order_components(s4, user_id),
        make_get_production_order_operations(s4, user_id),
        make_get_production_confirmations(s4, user_id),
        # Production Order — read OData V2 (API_PRODUCTION_ORDER_2_SRV)
        make_get_production_orders_odata(s4, user_id),
        make_get_production_order_status_odata(s4, user_id),
        make_get_production_order_components_odata(s4, user_id),
        make_get_production_order_operations_odata(s4, user_id),
        # Production Execution — write (OData V2)
        make_post_goods_issue_production(s4, user_id),
        make_post_production_confirmation(s4, user_id),
        make_post_goods_receipt_production(s4, user_id),
        # Purchase Orders / STOs (OData V4 — API_PURCHASEORDER_2)
        make_get_purchase_orders(s4, user_id),
        make_get_po_details(s4, user_id),
        # Batch Management (OData V2 — API_BATCH_SRV)
        make_search_batches(s4, user_id),
        make_get_batch_classification(s4, user_id),
    ]
