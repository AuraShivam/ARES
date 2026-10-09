from rest_framework.permissions import BasePermission


class IsSupplyChainApprover(BasePermission):
    message = "Approval decisions require the ARES approver role."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_staff or user.groups.filter(name="ares_approvers").exists())
        )
