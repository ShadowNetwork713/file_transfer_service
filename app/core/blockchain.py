import logging
from collections.abc import Sequence

from app.core.block import GENESIS_PREV_HASH, Block
from app.core.hashing import IHashService
from app.core.record import Record
from app.core.storage import ChainStorageError, IChainRepository
from app.core.validation import ValidationReport, validate_blocks

GENESIS_TIMESTAMP = 0

logger = logging.getLogger(__name__)


class InvalidChainError(Exception):
    pass


class Blockchain:
    # цепочку берём из блоков или из хранилища, без них начинаем с genesis
    def __init__(
        self,
        hash_service: IHashService,
        blocks: Sequence[Block] | None = None,
        repository: IChainRepository | None = None,
    ):
        self._hash_service = hash_service
        self._repository = repository
        self._blocked = False
        self._blocks = list(blocks) if blocks else []
        if not self._blocks and repository is not None:
            self._load_from_repository()
        if not self._blocks:
            self._blocks = [self.create_genesis()]
            self._save(self._blocks)
        elif not self._blocked and not self.validate_chain():
            self._block("цепочка повреждена после загрузки")

    # читает блоки из хранилища, при ошибке чтения блокирует добавление
    def _load_from_repository(self) -> None:
        try:
            self._blocks = self._repository.load_chain()
        except ChainStorageError:
            logger.exception("не удалось прочитать цепочку из хранилища")
            self._blocks = [self.create_genesis()]
            self._blocked = True

    # блокирует добавление блоков и пишет ошибку в лог
    def _block(self, reason: str) -> None:
        self._blocked = True
        logger.error("%s, добавление блоков запрещено", reason)

    # сохраняет блоки, если хранилище подключено
    def _save(self, blocks: Sequence[Block]) -> None:
        if self._repository is not None:
            self._repository.save_chain(blocks)

    # genesis создаётся вручную с фиксированными полями, поэтому он всегда одинаковый
    def create_genesis(self) -> Block:
        return Block.create(
            0,
            GENESIS_PREV_HASH,
            [],
            self._hash_service,
            timestamp=GENESIS_TIMESTAMP,
        )

    # блоки цепочки только для чтения
    @property
    def blocks(self) -> tuple[Block, ...]:
        return tuple(self._blocks)

    # последний блок цепочки
    @property
    def last_block(self) -> Block:
        return self._blocks[-1]

    # добавление заблокировано, если цепочка не прошла проверку при загрузке
    @property
    def is_blocked(self) -> bool:
        return self._blocked

    # количество блоков вместе с genesis
    def __len__(self) -> int:
        return len(self._blocks)

    # добавляет блок с записями, хеш и ссылка на предыдущий блок считаются сами
    def add_block(self, records: Sequence[Record]) -> Block:
        if not records:
            raise ValueError("нельзя добавить блок без записей")
        if not self.validate_chain():
            raise InvalidChainError("цепочка повреждена, добавление блоков запрещено")
        block = Block.create(
            self.last_block.index + 1,
            self.last_block.hash,
            records,
            self._hash_service,
        )
        self._save([*self._blocks, block])
        self._blocks.append(block)
        return block

    # полный отчёт проверки блоков: номер, genesis, хеши блоков и записей, ссылки
    def validate_report(self) -> ValidationReport:
        return validate_blocks(self._blocks, self._hash_service)

    # цепочка валидна, если она не заблокирована и в отчёте нет нарушений
    def validate_chain(self) -> bool:
        return not self._blocked and self.validate_report().is_valid
