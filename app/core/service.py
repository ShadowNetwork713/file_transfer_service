import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import BinaryIO, Protocol

from app.core.blockchain import Blockchain, InvalidChainError
from app.core.hashing import IHashService
from app.core.record import Record
from app.core.storage import ChainStorageError

logger = logging.getLogger(__name__)


class RegistrationStatus(StrEnum):
    # запись принята, но ещё не попала в блок
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RegistrationResult:
    tx_id: str | None
    block_index: int | None
    status: RegistrationStatus
    error: str | None = None


class FileCheckStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    NOT_FOUND = "NOT_FOUND"
    CHAIN_INVALID = "CHAIN_INVALID"


@dataclass(frozen=True)
class FileCheckResult:
    status: FileCheckStatus
    message: str
    current_hash: str
    registered_hash: str | None = None
    block_index: int | None = None


class IBlockchainService(Protocol):
    # регистрирует хеш документа, при сбое отдаёт FAILED и позволяет повторить
    def register_document(
        self, document_id: str, file_hash: str
    ) -> RegistrationResult: ...

    # проверяет целостность всей цепочки
    def validate_chain(self) -> bool: ...

    # сверяет хеш файла с хешем, зарегистрированным для документа
    def verify_file(self, document_id: str, stream: BinaryIO) -> FileCheckResult: ...


class BlockchainService:
    def __init__(self, blockchain: Blockchain, hash_service: IHashService):
        self._blockchain = blockchain
        self._hash_service = hash_service

    # регистрирует хеш документа в новом блоке, повтор той же регистрации блок не плодит
    def register_document(self, document_id: str, file_hash: str) -> RegistrationResult:
        existing = self._find_record(document_id, file_hash)
        if existing is not None:
            return self._confirmed(*existing)
        record = Record.create(document_id, file_hash, self._hash_service)
        try:
            block = self._blockchain.add_block([record])
        except (InvalidChainError, ChainStorageError, OSError) as error:
            logger.error("регистрация документа %s не удалась: %s", document_id, error)
            return RegistrationResult(None, None, RegistrationStatus.FAILED, str(error))
        return self._confirmed(record, block.index)

    # проверяет целостность всей цепочки
    def validate_chain(self) -> bool:
        return self._blockchain.validate_chain()

    # сверяет файл с последней записью документа, на битой цепочке не подтверждает
    def verify_file(self, document_id: str, stream: BinaryIO) -> FileCheckResult:
        current_hash = self._hash_service.hash_stream(stream)
        if not self._blockchain.validate_chain():
            issue = self._blockchain.find_break()
            reason = issue.message if issue else "цепочка заблокирована"
            return FileCheckResult(
                FileCheckStatus.CHAIN_INVALID,
                f"Проверить файл нельзя: цепочка повреждена. {reason}",
                current_hash,
            )
        records = self._blockchain.find_records(document_id)
        if not records:
            return FileCheckResult(
                FileCheckStatus.NOT_FOUND,
                "Документ не найден в цепочке",
                current_hash,
            )
        record, block_index = records[-1]
        if record.file_hash == current_hash:
            return FileCheckResult(
                FileCheckStatus.VALID,
                f"Целостность файла подтверждена: хеш совпадает с зарегистрированным "
                f"(блок {block_index})",
                current_hash,
                record.file_hash,
                block_index,
            )
        return FileCheckResult(
            FileCheckStatus.INVALID,
            f"Целостность файла не подтверждена: содержимое отличается от "
            f"зарегистрированного (блок {block_index})",
            current_hash,
            record.file_hash,
            block_index,
        )

    # ищет запись с таким же документом и хешем файла
    def _find_record(
        self, document_id: str, file_hash: str
    ) -> tuple[Record, int] | None:
        for block in self._blockchain.blocks:
            for record in block.records:
                if record.document_id == document_id and record.file_hash == file_hash:
                    return record, block.index
        return None

    # результат успешной регистрации, transaction hash это хеш записи
    def _confirmed(self, record: Record, block_index: int) -> RegistrationResult:
        return RegistrationResult(
            record.record_hash, block_index, RegistrationStatus.CONFIRMED
        )
