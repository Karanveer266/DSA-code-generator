# 🤖 Agentic AI Workflow Engine with Secure Sandboxed Execution

A production-ready backend that turns a natural-language **algorithmic problem
statement** into a **verified, optimal C++ or Python solution** — fully
autonomously.

I used this exact architecture to get a global rank 4 in meta hackercup AI track round 2 and rank 24 in round 1 with 13000+ participants.

It does this with a **multi-agent LLM workflow** that writes code, a
**brute-force oracle** that establishes ground truth, a **secure Docker
sandbox** that runs untrusted generated code safely, and a **self-correction
loop** that repairs the solution until it is provably correct.

---

## ✨ Key idea: the brute force is the oracle

Instead of trusting an LLM's own claim that its code is correct, this engine
cross-checks two independently generated programs:

```
                        ┌──────────────────────┐
  Problem statement ──► │  1. Test Designer    │ ─► extra inputs + edge cases
                        └──────────────────────┘
                                   │
            ┌──────────────────────┴───────────────────────┐
            ▼                                               ▼
  ┌──────────────────────┐                      ┌──────────────────────┐
  │ 2. Brute-Force Coder │                      │ 3. Optimal Coder     │
  │  simple & correct    │                      │  fast & efficient    │
  └──────────┬───────────┘                      └──────────┬───────────┘
             │ run in sandbox on every input               │
             ▼                                              │
     GROUND-TRUTH outputs ◄───────── compare ──────────────┘ run in sandbox
             │                                              │
             └──────────────► match? ◄─────────────────────┘
                                │
                   ┌────────────┴─────────────┐
                 YES                          NO
                   │                           │
              ✅ SOLVED            ┌──────────────────────┐
                                   │ 4. Critic / Fixer    │ ─► rewrite optimal
                                   └──────────────────────┘    (≤ MAX_ATTEMPTS)
```

Because the brute force is written for **correctness, not speed**, we trust its
answers — so the user never has to supply expected outputs for the dozens of
auto-generated edge cases. The optimal solution is accepted **only** when it
matches the oracle on every case.

---

## 🧱 Tech stack

| Layer            | Technology                                            |
| ---------------- | ----------------------------------------------------- |
| API              | Django 5 + Django REST Framework                      |
| Async tasks      | Celery + Redis (or inline/eager mode)                 |
| LLM agents       | Anthropic Claude via the official `anthropic` SDK     |
| Sandboxing       | Docker Engine (sibling containers via the Docker SDK) |
| Target languages | C++17 (STL, fast I/O) and Python 3.11                 |

---

## 🔒 Security model (the sandbox)

Every piece of LLM-generated code runs in an **ephemeral, locked-down Docker
container**:

- `--network none` — no network access whatsoever.
- **256 MB** memory limit with swap disabled (OOM kills are detected).
- **3-second** CPU/wall-clock timeout (container is killed on overrun).
- **Read-only** root filesystem; code mounted read-only; small `noexec` tmpfs
  for scratch.
- **All Linux capabilities dropped** + `no-new-privileges`.
- Runs as the unprivileged `nobody` user.
- **PID limit** (128) to defeat fork bombs.
- Output captured and size-capped; the container is always force-removed.

The Django/Celery containers use the **sibling-container pattern**: they talk to
the host Docker daemon via a mounted socket and launch sandbox containers as
siblings (no Docker-in-Docker).

> ⚠️ Mounting `/var/run/docker.sock` grants host-daemon control to the backend
> containers. See [`details.md`](../details.md) for hardening options.

---

## 🚀 Quick start

### Option A — Docker Compose (recommended, full stack)

```bash
cd project
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...   (or leave blank for mock mode)

docker compose up --build
```

The API is now at **http://localhost:8000**.

Try it:

```bash
./examples/sample_request.sh
```

### Option B — Local, no Docker, no API key (instant demo)

The engine ships with an **offline mock LLM** and a **local subprocess
sandbox**, so the whole pipeline runs with zero external dependencies:

```bash
cd project
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export LLM_BACKEND=mock          # deterministic offline "LLM"
export SANDBOX_BACKEND=local     # subprocess runner (dev only!)
export RUN_TASKS_SYNC=1          # run tasks inline, no Celery/Redis needed

python manage.py migrate
python manage.py solve --file examples/two_sum.json
```

Or run the HTTP server the same way:

```bash
python manage.py runserver
```

---

## 📡 API reference

Base path: `/api/v1/`

### `POST /solve/` — submit a problem

Request body:

```json
{
  "problem_statement": "Read two integers a and b and print a + b.",
  "language": "python",
  "test_cases": [
    {"input": "2 3\n", "expected_output": "5"},
    {"input": "40 2\n", "expected_output": "42"}
  ]
}
```

- `language` — `"cpp"` or `"python"` (default `"cpp"`).
- `test_cases` — optional. `expected_output` is optional; when omitted the
  brute-force oracle supplies it. The test designer adds many more.

Response (`202 Accepted`):

```json
{
  "id": "0f8c...",
  "status": "pending",
  "poll_url": "http://localhost:8000/api/v1/solve/0f8c.../"
}
```

### `GET /solve/<id>/` — poll status + result

Returns the job including live `progress`, and once finished, a `result` with:

```json
{
  "status": "succeeded",
  "result": {
    "success": true,
    "status": "solved",
    "message": "Optimal solution verified against brute force ...",
    "language": "python",
    "final_code": "...",
    "brute_force_code": "...",
    "attempts_used": 1,
    "attempts": [ ... per-test-case results ... ],
    "all_test_cases": [ ... ],
    "log": [ ... ]
  }
}
```

### `GET /solve/list/` — list recent jobs

### `GET /health/` — liveness probe + active engine config

---

## ⚙️ Configuration

All configuration is via environment variables (see
[`.env.example`](.env.example)). Highlights:

| Variable                   | Default            | Purpose                                   |
| -------------------------- | ------------------ | ----------------------------------------- |
| `ANTHROPIC_API_KEY`        | —                  | Claude API key (blank ⇒ mock backend)     |
| `LLM_BACKEND`              | `anthropic`        | `anthropic` or `mock`                     |
| `LLM_MODEL`                | `claude-opus-5-5`  | Claude model id                           |
| `LLM_EFFORT`               | `high`             | Reasoning effort: `low`…`max`             |
| `MAX_ATTEMPTS`             | `3`                | Self-correction retry limit               |
| `GENERATED_TESTCASE_COUNT` | `12`               | Extra cases the test designer invents     |
| `SANDBOX_BACKEND`          | `docker`           | `docker` (secure) or `local` (dev only)   |
| `SANDBOX_MEMORY_LIMIT`     | `256m`             | Container memory cap                       |
| `SANDBOX_CPU_TIMEOUT`      | `3`                | Per-run time limit (seconds)              |
| `RUN_TASKS_SYNC`           | `0`                | `1` ⇒ run tasks inline (no worker needed) |

---

## 🧪 Tests

```bash
# Uses mock LLM + local sandbox; no Docker or API key required.
RUN_TASKS_SYNC=1 LLM_BACKEND=mock SANDBOX_BACKEND=local \
  python manage.py test api
```

The suite covers code extraction, output normalisation, the mock LLM, the
full orchestrator loop (Python and C++), and every API endpoint.

---

## 📁 Project structure

```
project/
├── config/              # Django project (settings, urls, wsgi/asgi, celery)
├── api/                 # DRF app: models, serializers, views, tasks, admin
│   ├── management/commands/solve.py   # CLI solve command
│   └── tests/           # engine + API tests
├── engine/              # Framework-agnostic agentic engine
│   ├── orchestrator.py  # the agentic control loop (the heart)
│   ├── agents.py        # the four agent roles
│   ├── prompts.py       # system/user prompts
│   ├── llm_client.py    # Anthropic + mock backends
│   ├── sandbox.py       # Docker + local sandbox backends
│   ├── mock_solutions.py# offline deterministic "LLM"
│   ├── schemas.py       # typed dataclasses
│   └── config.py        # env/Django config loader
├── examples/            # sample payloads + curl script
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
└── requirements.txt
```

---

## 📝 License

MIT. See [`details.md`](../details.md) for the full feature list and design notes.

