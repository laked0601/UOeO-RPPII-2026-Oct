"""
Writing JSON files the same way everywhere: accents and the pound sign left readable.
Results are indented so people can read them; the OCR cache is for the program, so it is written compactly.
"""

import json


def write_json(path, data, indent=2):
    """Write `data` to `path` via a temporary file, so a run stopped part way never leaves half a file."""
    separators = None if indent else (",", ":")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=indent, ensure_ascii=False, separators=separators), encoding="utf-8")
    temporary.replace(path)
