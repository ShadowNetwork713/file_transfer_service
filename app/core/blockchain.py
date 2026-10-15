from collections.abc import Sequence

from app.core.block import GENESIS_PREV_HASH, Block
from app.core.hashing import IHashService
from app.core.record import Record

GENESIS_TIMESTAMP = 0


class InvalidChainError(Exception):
    pass


class Blockchain:
    # без переданных блоков цепочка начинается с genesis
    def __init__(
        self, hash_service: IHashService, blocks: Sequence[Block] | None = None
    ):
        self._hash_service = hash_service
        self._blocks = list(blocks) if blocks else [self.create_genesis()]

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
        self._blocks.append(block)
        return block

    # проверяет genesis, а у каждого блока номер, хеш и ссылку на предыдущий
    def validate_chain(self) -> bool:
        first = self._blocks[0]
        if first.index != 0 or first.prev_hash != GENESIS_PREV_HASH:
            return False
        for position, block in enumerate(self._blocks):
            if block.index != position or not block.verify(self._hash_service):
                return False
            if position > 0 and block.prev_hash != self._blocks[position - 1].hash:
                return False
        return True
