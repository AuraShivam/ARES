from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from supply_chain.import_views import import_commit, import_detail, import_preview, import_templates, imports_list
from supply_chain.auth_views import current_user, login, logout
from supply_chain.feed_views import feed_status
from supply_chain.views import (
    AuditEventViewSet, DisruptionViewSet, InventoryMovementViewSet, InventoryViewSet,
    MaterialViewSet, NotificationDeliveryViewSet, PurchaseOrderLineViewSet, PurchaseOrderViewSet,
    ResponseActionViewSet,
    ResponsePlanViewSet, RiskAlertViewSet, RiskAssessmentViewSet, ShipmentViewSet,
    SupplierViewSet, WarehouseViewSet, health, overview, risk_assess,
    risk_calibration, risk_outcome_upsert, risk_policy,
)

router = DefaultRouter()
router.register("suppliers", SupplierViewSet)
router.register("materials", MaterialViewSet)
router.register("warehouses", WarehouseViewSet)
router.register("inventory", InventoryViewSet)
router.register("inventory-movements", InventoryMovementViewSet)
router.register("purchase-orders", PurchaseOrderViewSet)
router.register("purchase-order-lines", PurchaseOrderLineViewSet)
router.register("response-plans", ResponsePlanViewSet)
router.register("response-actions", ResponseActionViewSet)
router.register("shipments", ShipmentViewSet)
router.register("disruptions", DisruptionViewSet)
router.register("audit-events", AuditEventViewSet)
router.register("risk/assessments", RiskAssessmentViewSet, basename="risk-assessment")
router.register("risk/alerts", RiskAlertViewSet, basename="risk-alert")
router.register("notifications", NotificationDeliveryViewSet, basename="notification-delivery")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/login/", login, name="api-login"),
    path("api/auth/me/", current_user, name="api-current-user"),
    path("api/auth/logout/", logout, name="api-logout"),
    path("api/", include(router.urls)),
    path("api/imports/templates/", import_templates, name="import-templates"),
    path("api/feeds/status/", feed_status, name="feed-status"),
    path("api/imports/preview/", import_preview, name="import-preview"),
    path("api/imports/<uuid:batch_id>/commit/", import_commit, name="import-commit"),
    path("api/imports/<uuid:batch_id>/", import_detail, name="import-detail"),
    path("api/imports/", imports_list, name="imports-list"),
    path("api/overview/", overview, name="overview"),
    path("api/risk/assess/", risk_assess, name="risk-assess"),
    path("api/risk/policy/", risk_policy, name="risk-policy"),
    path("api/risk/outcomes/", risk_outcome_upsert, name="risk-outcome-upsert"),
    path("api/risk/calibration/", risk_calibration, name="risk-calibration"),
    path("api/health/", health, name="health"),
]

handler404 = "config.api_errors.api_not_found"
handler500 = "config.api_errors.api_server_error"
