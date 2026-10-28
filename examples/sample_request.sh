#!/usr/bin/env bash
# =========================================================================
# Example: submit a problem to the API and poll until it finishes.
# Requires: curl, jq.
# =========================================================================
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

echo "==> Submitting solve job..."
RESPONSE=$(curl -sS -X POST "${BASE_URL}/api/v1/solve/" \
    -H "Content-Type: application/json" \
    -d '{
      "problem_statement": "Read two integers a and b and print a + b.",
      "language": "python",
      "test_cases": [
        {"input": "2 3\n", "expected_output": "5"},
        {"input": "40 2\n", "expected_output": "42"}
      ]
    }')

echo "$RESPONSE" | jq .
JOB_ID=$(echo "$RESPONSE" | jq -r .id)
echo "==> Job id: ${JOB_ID}"

echo "==> Polling..."
while true; do
    JOB=$(curl -sS "${BASE_URL}/api/v1/solve/${JOB_ID}/")
    STATUS=$(echo "$JOB" | jq -r .status)
    echo "    status=${STATUS}"
    case "$STATUS" in
        succeeded|failed|error)
            echo "==> Final result:"
            echo "$JOB" | jq '{status, result: {success: .result.success, status: .result.status, message: .result.message, attempts_used: .result.attempts_used}}'
            echo "==> Final code:"
            echo "$JOB" | jq -r .result.final_code
            break
            ;;
    esac
    sleep 2
done
