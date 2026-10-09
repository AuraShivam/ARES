from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from supply_chain.views import (
    DisruptionViewSet, InventoryViewSet, MaterialViewSet, PurchaseOrderViewSet,
    ShipmentViewSet, SupplierViewSet, health, overview, risk_assess,
)

router = DefaultRouter()
router.register("suppliers", SupplierViewSet)
router.register("materials", MaterialViewSet)
router.register("inventory", InventoryViewSet)
router.register("purchase-orders", PurchaseOrderViewSet)
router.register("shipments", ShipmentViewSet)
router.register("disruptions", DisruptionViewSet)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api/overview/", overview, name="overview"),
    path("api/risk/assess/", risk_assess, name="risk-assess"),
    path("api/health/", health, name="health"),
]
