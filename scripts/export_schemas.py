"""Run with `uv run python -m scripts.export_schemas`."""
import json
from pathlib import Path

from contracts import models


def main():
    target = Path(__file__).resolve().parents[1] / "contracts/schema"
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for name, cls in vars(models).items():
        if isinstance(cls, type) and issubclass(cls, models.Model):
            (target / f"{name}.json").write_text(
                json.dumps(cls.model_json_schema(), indent=2, ensure_ascii=False) + "\n")
            count += 1
    print(f"Exported {count} schemas to contracts/schema")


if __name__ == "__main__":
    main()
