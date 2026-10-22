import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from app.core.block import Block

STORAGE_VERSION = 1


class ChainStorageError(Exception):
    pass


class IChainRepository(Protocol):
    # все сохранённые блоки, пустой список если цепочки ещё нет
    def load_chain(self) -> list[Block]: ...

    # сохраняет всю цепочку целиком
    def save_chain(self, blocks: Sequence[Block]) -> None: ...


class JsonChainRepository:
    def __init__(self, path: str | Path):
        self._path = Path(path)

    # читает цепочку из json, отсутствие файла значит пустую цепочку
    def load_chain(self) -> list[Block]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [Block.from_dict(item) for item in raw["blocks"]]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ChainStorageError(f"не удалось прочитать {self._path}") from error

    # пишет цепочку во временный файл и подменяет им основной
    def save_chain(self, blocks: Sequence[Block]) -> None:
        data = {
            "version": STORAGE_VERSION,
            "blocks": [block.to_dict() for block in blocks],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                json.dump(data, temp_file, ensure_ascii=False, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, self._path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
