from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Self

from app.core.canonical import to_canonical_json
from app.core.hashing import IHashService
from app.core.record import Record, now_ms

GENESIS_PREV_HASH = "0" * 64


@dataclass
class Block:
    index: int
    timestamp: int
    prev_hash: str
    records: list[Record]
    hash: str

    # создаёт блок и считает его хеш
    @classmethod
    def create(
        cls,
        index: int,
        prev_hash: str,
        records: Sequence[Record],
        hash_service: IHashService,
        timestamp: int | None = None,
    ) -> Self:
        timestamp = timestamp if timestamp is not None else now_ms()
        block = cls(index, timestamp, prev_hash, list(records), "")
        block.hash = block.compute_hash(hash_service)
        return block

    # заголовок блока: из него считается хеш, записи входят через их хеши
    def _header(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "prevHash": self.prev_hash,
            "recordHashes": [record.record_hash for record in self.records],
        }

    # канонический json заголовка
    def to_canonical_json(self) -> str:
        return to_canonical_json(self._header())

    # хеш блока по каноническому json заголовка
    def compute_hash(self, hash_service: IHashService) -> str:
        return hash_service.hash_text(self.to_canonical_json())

    # хеш блока и хеш каждой записи совпадают с пересчитанными
    def verify(self, hash_service: IHashService) -> bool:
        if self.hash != self.compute_hash(hash_service):
            return False
        return all(record.verify(hash_service) for record in self.records)

    # блок в виде словаря для json
    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "prevHash": self.prev_hash,
            "records": [record.to_dict() for record in self.records],
            "hash": self.hash,
        }

    # собирает блок из словаря
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            index=data["index"],
            timestamp=data["timestamp"],
            prev_hash=data["prevHash"],
            records=[Record.from_dict(item) for item in data["records"]],
            hash=data["hash"],
        )
