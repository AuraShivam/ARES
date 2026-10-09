from django.contrib import admin
from .models import (AuditEvent, Disruption, Inventory, InventoryMovement, Material,
                     PurchaseOrder, PurchaseOrderLine, Shipment, Supplier, Warehouse)

for model in (Supplier, Material, Warehouse, Inventory, InventoryMovement,
              PurchaseOrder, PurchaseOrderLine, Shipment, Disruption, AuditEvent):
    admin.site.register(model)
