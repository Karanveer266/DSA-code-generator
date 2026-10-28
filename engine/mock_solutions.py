"""
Deterministic offline "LLM" used by :class:`engine.llm_client.MockLLMClient`.

This lets the whole agentic workflow run end-to-end with **no API key and no
network** - essential for CI, tests, and a first-run demo. It is not a real
model: it recognises a small catalogue of classic problems by keyword and
returns working C++/Python plus matching generated test inputs. For anything
outside the catalogue it falls back to a generic "sum of N integers" template,
which keeps the pipeline exercised even if the canned code does not solve the
user's exact problem.
"""

from __future__ import annotations

import json
import random

# ---------------------------------------------------------------------------
# Agent detection - which agent is asking?
# ---------------------------------------------------------------------------
_CPP_MARKER = "C++"
_PY_MARKER = "Python 3"


def _is_cpp(system: str) -> bool:
    # The coder/critic system prompts name the target language explicitly.
    return "C++" in system and "Python 3" not in system


def _agent_kind(system: str) -> str:
    if "test designer" in system.lower():
        return "test_designer"
    if "reference" in system.lower() or "brute-force" in system.lower():
        return "brute_force"
    if "debugger" in system.lower() or "FAILED verification" in system:
        return "critic"
    return "optimal"


# ---------------------------------------------------------------------------
# Problem catalogue
# ---------------------------------------------------------------------------
# Each entry: keyword predicate + code/templates. "optimal" and "brute" may be
# identical for simple problems; the workflow still verifies them against each
# other, which is the point.

_SUM_TWO_CPP = """\
#include <bits/stdc++.h>
using namespace std;
int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);
    long long a, b;
    cin >> a >> b;
    cout << a + b << "\\n";
    return 0;
}
"""

_SUM_TWO_PY = """\
import sys

def main():
    data = sys.stdin.read().split()
    a, b = int(data[0]), int(data[1])
    print(a + b)

if __name__ == "__main__":
    main()
"""

_SUM_N_CPP = """\
#include <bits/stdc++.h>
using namespace std;
int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);
    int n;
    if (!(cin >> n)) return 0;
    long long total = 0, x;
    for (int i = 0; i < n; ++i) { cin >> x; total += x; }
    cout << total << "\\n";
    return 0;
}
"""

_SUM_N_PY = """\
import sys

def main():
    data = sys.stdin.buffer.read().split()
    if not data:
        return
    n = int(data[0])
    total = sum(int(v) for v in data[1:1 + n])
    print(total)

if __name__ == "__main__":
    main()
"""

_MAX_SUBARRAY_CPP = """\
#include <bits/stdc++.h>
using namespace std;
int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);
    int n;
    if (!(cin >> n)) return 0;
    long long best = LLONG_MIN, cur = 0;
    for (int i = 0; i < n; ++i) {
        long long x; cin >> x;
        cur = max(x, cur + x);
        best = max(best, cur);
    }
    cout << best << "\\n";
    return 0;
}
"""

_MAX_SUBARRAY_PY = """\
import sys

def main():
    data = sys.stdin.buffer.read().split()
    if not data:
        return
    n = int(data[0])
    nums = [int(v) for v in data[1:1 + n]]
    best = cur = nums[0]
    for x in nums[1:]:
        cur = max(x, cur + x)
        best = max(best, cur)
    print(best)

if __name__ == "__main__":
    main()
"""


def _catalogue(problem: str):
    """Return (cpp_code, py_code, input_generator) for the detected problem."""
    p = problem.lower()

    if "maximum subarray" in p or "max subarray" in p or "kadane" in p:
        return _MAX_SUBARRAY_CPP, _MAX_SUBARRAY_PY, _gen_array_inputs

    if ("sum of two" in p or "two integers" in p or "a + b" in p
            or "a+b" in p):
        return _SUM_TWO_CPP, _SUM_TWO_PY, _gen_two_int_inputs

    # Default fallback: sum of N integers.
    return _SUM_N_CPP, _SUM_N_PY, _gen_array_inputs


# ---------------------------------------------------------------------------
# Test-input generators
# ---------------------------------------------------------------------------
def _gen_two_int_inputs(count: int) -> list[dict]:
    rng = random.Random(1234)
    cases = [
        {"input": "0 0\n", "note": "zeros"},
        {"input": "-5 5\n", "note": "cancel to zero"},
        {"input": "1000000000 1000000000\n", "note": "overflow stressor"},
    ]
    while len(cases) < count:
        a, b = rng.randint(-10**9, 10**9), rng.randint(-10**9, 10**9)
        cases.append({"input": f"{a} {b}\n", "note": "random"})
    return cases[:count]


def _gen_array_inputs(count: int) -> list[dict]:
    rng = random.Random(4321)
    cases = [
        {"input": "1\n0\n", "note": "single zero"},
        {"input": "1\n-7\n", "note": "single negative"},
        {"input": "5\n1 2 3 4 5\n", "note": "sorted ascending"},
        {"input": "5\n-1 -2 -3 -4 -5\n", "note": "all negative"},
    ]
    while len(cases) < count:
        n = rng.randint(1, 50)
        arr = [rng.randint(-1000, 1000) for _ in range(n)]
        cases.append(
            {"input": f"{n}\n{' '.join(map(str, arr))}\n", "note": "random"}
        )
    return cases[:count]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def _extract_problem(user: str) -> str:
    """Pull the problem statement out of a user prompt."""
    marker = "Problem statement:"
    if marker in user:
        tail = user.split(marker, 1)[1]
        # Cut at the next structural marker if present.
        for stop in ("\n\nProduce", "\n\nWrite", "\n\nThe current"):
            if stop in tail:
                tail = tail.split(stop, 1)[0]
        return tail.strip()
    return user.strip()


def _requested_count(user: str, default: int = 12) -> int:
    import re

    m = re.search(r"about (\d+)", user)
    return int(m.group(1)) if m else default


def mock_completion(system: str, user: str) -> str:
    """Return a canned response appropriate to the calling agent."""
    kind = _agent_kind(system)
    problem = _extract_problem(user)
    cpp_code, py_code, gen = _catalogue(problem)

    if kind == "test_designer":
        count = _requested_count(user)
        return json.dumps({"test_cases": gen(count)}, indent=2)

    # Coder / critic: return source code in the requested language.
    return cpp_code if _is_cpp(system) else py_code
