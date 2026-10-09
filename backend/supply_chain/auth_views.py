from django.contrib.auth import authenticate
from rest_framework import serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    scope = "auth_login"


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False)


def user_payload(user):
    return {
        "id": user.pk,
        "username": user.get_username(),
        "display_name": user.get_full_name().strip() or user.get_username(),
        "is_approver": bool(user.is_staff or user.groups.filter(name="ares_approvers").exists()),
    }


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([LoginRateThrottle])
def login(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = authenticate(request, **serializer.validated_data)
    if user is None or not user.is_active:
        return Response({"detail": "Invalid username or password."}, status=status.HTTP_401_UNAUTHORIZED)

    # Keep one active API token per account so a fresh login invalidates an old one.
    Token.objects.filter(user=user).delete()
    token = Token.objects.create(user=user)
    return Response({"token": token.key, "user": user_payload(user)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_user(request):
    return Response(user_payload(request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
