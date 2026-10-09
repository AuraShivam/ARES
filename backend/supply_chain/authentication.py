from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed


class ExpiringTokenAuthentication(TokenAuthentication):
    model = Token

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        lifetime_hours = settings.ARES_API_TOKEN_TTL_HOURS
        if token.created < timezone.now() - timedelta(hours=lifetime_hours):
            token.delete()
            raise AuthenticationFailed("Your ARES session expired. Sign in again.")
        return user, token
