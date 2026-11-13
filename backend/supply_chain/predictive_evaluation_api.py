"""Authenticated API for creating and reviewing persisted model evaluations."""

from rest_framework import serializers, status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .models import PredictiveEvaluationRun
from .serializers import PredictiveEvaluationRunSerializer
from .predictive_evaluation import run_predictive_evaluation


class PredictiveEvaluationThrottle(UserRateThrottle):
    scope = "predictive_evaluation"

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


class PredictiveEvaluationRequestSerializer(serializers.Serializer):
    model = serializers.ChoiceField(choices=("shipment_delay", "material_demand"))
    as_of_date = serializers.DateField(required=False)


@api_view(["GET", "POST"])
@throttle_classes([PredictiveEvaluationThrottle])
def predictive_evaluations(request):
    if request.method == "POST":
        serializer = PredictiveEvaluationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            run = run_predictive_evaluation(
                model_type=serializer.validated_data["model"],
                as_of_date=serializer.validated_data.get("as_of_date"),
                requested_by=request.user,
            )
        except ValueError as exc:
            raise serializers.ValidationError({"as_of_date": str(exc)}) from exc
        return Response(PredictiveEvaluationRunSerializer(run).data, status=status.HTTP_201_CREATED)

    runs = PredictiveEvaluationRun.objects.all()
    model_type = request.query_params.get("model")
    run_status = request.query_params.get("status")
    if model_type:
        if model_type not in {choice[0] for choice in PredictiveEvaluationRun.MODEL_TYPES}:
            raise serializers.ValidationError({"model": "Choose shipment_delay or material_demand."})
        runs = runs.filter(model_type=model_type)
    if run_status:
        if run_status not in {choice[0] for choice in PredictiveEvaluationRun.STATUSES}:
            raise serializers.ValidationError({"status": "Choose a valid evaluation status."})
        runs = runs.filter(status=run_status)
    data = PredictiveEvaluationRunSerializer(runs[:50], many=True).data
    return Response({"count": len(data), "results": data})


@api_view(["GET"])
def predictive_evaluation_detail(request, evaluation_id):
    try:
        run = PredictiveEvaluationRun.objects.get(pk=evaluation_id)
    except PredictiveEvaluationRun.DoesNotExist as exc:
        raise NotFound("Predictive evaluation run not found.") from exc
    return Response(PredictiveEvaluationRunSerializer(run).data)
