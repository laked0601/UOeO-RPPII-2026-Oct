"""Writing JSON files the same way everywhere: indented, and with accents and the pound sign left readable."""

import json


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
