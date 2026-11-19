"""契约自检：能解析、路径齐全、错误信封字段一致。"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REQUIRED_ERROR_FIELDS = {"code", "message", "request_id", "details"}


def main() -> int:
    text = (ROOT / "openapi.yaml").read_text(encoding="utf-8")
    spec = yaml.safe_load(text)
    def check_refs(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref is not None:
                if not ref.startswith("#/"):
                    raise ValueError(f"契约只使用本地引用：{ref}")
                target = spec
                for key in ref[2:].split("/"):
                    target = target[key.replace("~1", "/").replace("~0", "~")]
            for value in node.values():
                check_refs(value)
        elif isinstance(node, list):
            for value in node:
                check_refs(value)
    check_refs(spec)
    paths = sorted(spec.get("paths", {}))
    schemas = sorted(spec.get("components", {}).get("schemas", {}))
    error_fields = set(spec["components"]["schemas"]["Error"]["required"])
    if error_fields != REQUIRED_ERROR_FIELDS:
        print(f"错误信封字段不符：{sorted(error_fields)}", file=sys.stderr)
        return 1
    examples = sorted(p.name for p in (ROOT / "examples").glob("*.json"))
    for name in examples:
        body = json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))
        if name.startswith("error-") and set(body) != REQUIRED_ERROR_FIELDS:
            raise ValueError(f"错误样例信封不符：{name}")
    print(f"openapi.yaml 可解析；路径 {len(paths)} 个，组件 {len(schemas)} 个，样例 {len(examples)} 个")
    for path in paths:
        print("  path", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
