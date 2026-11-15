"""契约自检：能解析、路径齐全、错误信封字段一致。"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REQUIRED_ERROR_FIELDS = {"code", "message", "request_id", "details"}


def main() -> int:
    text = (ROOT / "openapi.yaml").read_text(encoding="utf-8")
    spec = yaml.safe_load(text)
    paths = sorted(spec.get("paths", {}))
    schemas = sorted(spec.get("components", {}).get("schemas", {}))
    error_fields = set(spec["components"]["schemas"]["Error"]["required"])
    if error_fields != REQUIRED_ERROR_FIELDS:
        print(f"错误信封字段不符：{sorted(error_fields)}", file=sys.stderr)
        return 1
    examples = sorted(p.name for p in (ROOT / "examples").glob("*.json"))
    print(f"openapi.yaml 可解析；路径 {len(paths)} 个，组件 {len(schemas)} 个，样例 {len(examples)} 个")
    for path in paths:
        print("  path", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
