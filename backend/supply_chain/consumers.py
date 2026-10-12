import asyncio
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from .authentication import ExpiringTokenAuthentication


DASHBOARD_GROUP = "ares.dashboard.events"


@database_sync_to_async
def _user_for_token(key):
    try:
        user, _token = ExpiringTokenAuthentication().authenticate_credentials(key)
    except AuthenticationFailed:
        return None
    if not user.is_active:
        return None
    expires_at = _token.created + timedelta(hours=settings.ARES_API_TOKEN_TTL_HOURS)
    remaining_seconds = max(0, (expires_at - timezone.now()).total_seconds())
    return user, remaining_seconds


class DashboardEventsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = None
        self.authenticating = False
        self.joined_group = False
        self.auth_timeout = asyncio.create_task(self._close_if_unauthenticated())
        await self.accept()

    async def _close_if_unauthenticated(self):
        await asyncio.sleep(5)
        if self.user is None:
            await self.close(code=4401)

    async def receive_json(self, content, **kwargs):
        if self.user is not None or self.authenticating:
            return
        if not isinstance(content, dict) or content.get("type") != "authenticate":
            await self.close(code=4401)
            return

        key = content.get("token")
        if not isinstance(key, str) or not key or len(key) > 128:
            await self.close(code=4401)
            return

        self.authenticating = True
        self.auth_timeout.cancel()
        authenticated = await _user_for_token(key)
        if authenticated is None:
            await self.close(code=4401)
            return

        user, remaining_seconds = authenticated
        self.user = user
        self.expiry_timeout = asyncio.create_task(self._close_when_token_expires(remaining_seconds))
        await self.channel_layer.group_add(DASHBOARD_GROUP, self.channel_name)
        self.joined_group = True
        await self.send_json({"type": "ready"})

    async def _close_when_token_expires(self, remaining_seconds):
        await asyncio.sleep(remaining_seconds)
        await self.close(code=4401)

    async def dashboard_data_changed(self, event):
        if self.user is not None:
            await self.send_json({
                "type": "data_changed",
                "resource": event["resource"],
                "action": event["action"],
            })

    async def disconnect(self, close_code):
        if hasattr(self, "auth_timeout"):
            self.auth_timeout.cancel()
        if hasattr(self, "expiry_timeout"):
            self.expiry_timeout.cancel()
        if self.joined_group:
            await self.channel_layer.group_discard(DASHBOARD_GROUP, self.channel_name)
