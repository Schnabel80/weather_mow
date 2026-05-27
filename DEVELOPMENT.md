# Development

## Setup

```bash
uv sync
```

## Commands

Format code:
```bash
uv run ruff format .
```

Check formatting without applying changes:
```bash
uv run ruff format --check .
```

Lint:
```bash
uv run ruff check .
```

Type check:
```bash
uv run ty check
```

Run tests:
```bash
uv run pytest
```
