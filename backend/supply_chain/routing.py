from django.urls import path

from .consumers import DashboardEventsConsumer


websocket_urlpatterns = [
    path("ws/events/", DashboardEventsConsumer.as_asgi()),
]
