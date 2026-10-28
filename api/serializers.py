"""DRF serializers for request validation and response shaping."""

from __future__ import annotations

from rest_framework import serializers

from engine.schemas import Language

from .models import SolveJob


class TestCaseSerializer(serializers.Serializer):
    """One input/expected-output pair in the request payload."""

    input = serializers.CharField(
        allow_blank=True,
        trim_whitespace=False,
        help_text="Exact text piped to the program on stdin.",
    )
    expected_output = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        trim_whitespace=False,
        help_text="Optional expected stdout. If omitted, the brute-force "
        "reference solution supplies the ground truth.",
    )


class SolveRequestSerializer(serializers.Serializer):
    """Validates the body of ``POST /api/v1/solve/``."""

    problem_statement = serializers.CharField(
        min_length=1,
        trim_whitespace=False,
        help_text="Natural-language algorithmic problem statement.",
    )
    test_cases = TestCaseSerializer(
        many=True,
        required=False,
        default=list,
    )
    language = serializers.CharField(
        required=False,
        default="cpp",
        help_text="Target language: 'cpp' or 'python'.",
    )

    def validate_language(self, value: str) -> str:
        try:
            return Language.from_str(value).value
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class SolveJobSerializer(serializers.ModelSerializer):
    """Full representation of a job (status + results)."""

    class Meta:
        model = SolveJob
        fields = [
            "id",
            "status",
            "language",
            "problem_statement",
            "test_cases",
            "result",
            "progress",
            "error_message",
            "created_at",
            "updated_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields


class SolveJobSummarySerializer(serializers.ModelSerializer):
    """Compact representation for list endpoints."""

    class Meta:
        model = SolveJob
        fields = [
            "id",
            "status",
            "language",
            "created_at",
            "finished_at",
        ]
        read_only_fields = fields
