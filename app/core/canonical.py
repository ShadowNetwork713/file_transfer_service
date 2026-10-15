import json
from typing import Any


# канонический json: ключи по алфавиту, без пробелов, utf-8 без экранирования
def to_canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
