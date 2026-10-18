# nebius-hack
Nebius Build Week Hackathon (Tech Europe)

Read [context.md](context.md) and [plan.md](plan.md), then implement your assigned
member's scope on its assigned branch.

Member 1 platform setup and commands: [backend/core/README.md](backend/core/README.md).
Nebius deployment: [infra/README.md](infra/README.md).

```bash
uv sync --python 3.12
uv run uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 1
```
