import time
import uuid
from dataclasses import dataclass
from typing import Any, Self

from app.core.canonical import to_canonical_json
from app.core.hashing import IHashService, is_valid_hash


# текущее время в utc, unix ms
def now_ms() -> int:
    return time.time_ns() // 1_000_000


# проверяет, что строка это uuid в каноническом виде
def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


@dataclass(frozen=True)
class Record:
    record_id: str
    document_id: str
    file_hash: str
    timestamp: int
    record_hash: str

    # создаёт запись и считает её хеш
    @classmethod
    def create(
        cls,
        document_id: str,
        file_hash: str,
        hash_service: IHashService,
        record_id: str | None = None,
        timestamp: int | None = None,
    ) -> Self:
        record_id = record_id if record_id is not None else str(uuid.uuid4())
        timestamp = timestamp if timestamp is not None else now_ms()
        if not _is_uuid(record_id) or not _is_uuid(document_id):
            raise ValueError("идентификатор должен быть uuid в нижнем регистре")
        if not is_valid_hash(file_hash):
            raise ValueError("хеш файла должен быть hex в нижнем регистре длиной 64")
        record = cls(record_id, document_id, file_hash, timestamp, "")
        return cls(
            record_id,
            document_id,
            file_hash,
            timestamp,
            record.compute_hash(hash_service),
        )

    # поля записи без хеша, из них считается recordHash
    def _payload(self) -> dict[str, Any]:
        return {
            "recordId": self.record_id,
            "documentId": self.document_id,
            "fileHash": self.file_hash,
            "timestamp": self.timestamp,
        }

    # канонический json полей записи
    def to_canonical_json(self) -> str:
        return to_canonical_json(self._payload())

    # хеш записи по каноническому json
    def compute_hash(self, hash_service: IHashService) -> str:
        return hash_service.hash_text(self.to_canonical_json())

    # сохранённый хеш совпадает с пересчитанным
    def verify(self, hash_service: IHashService) -> bool:
        return self.record_hash == self.compute_hash(hash_service)

    # запись в виде словаря для json
    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "recordHash": self.record_hash}

    # собирает запись из словаря
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            record_id=data["recordId"],
            document_id=data["documentId"],
            file_hash=data["fileHash"],
            timestamp=data["timestamp"],
            record_hash=data["recordHash"],
        )
