import json
import os
from typing import Any, Dict, List


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Any) -> None:
    _ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_hits_json(path: str, new_hits: List[Dict[str, str]]) -> None:
    """Append hits to the JSON file incrementally (read-modify-write)."""
    existing = load_json(path, [])
    existing.extend(new_hits)
    save_json(path, existing)


def append_csv(path: str, rows: List[Dict[str, str]]) -> None:
    if not rows:
        return
    _ensure_dir(os.path.dirname(path))
    file_exists = os.path.exists(path)
    headers = list(rows[0].keys())
    with open(path, "a", encoding="utf-8") as f:
        if not file_exists:
            f.write(",".join(headers) + "\n")
        for row in rows:
            values = [str(row.get(h, "")).replace("\n", " ").replace("\r", " ") for h in headers]
            safe = ["\"" + v.replace("\"", "\"\"") + "\"" for v in values]
            f.write(",".join(safe) + "\n")
