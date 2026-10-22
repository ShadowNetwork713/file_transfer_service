from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.core.block import GENESIS_PREV_HASH, Block
from app.core.hashing import IHashService


class IssueCode(StrEnum):
    EMPTY_CHAIN = "EMPTY_CHAIN"
    GENESIS_INVALID = "GENESIS_INVALID"
    INDEX_MISMATCH = "INDEX_MISMATCH"
    BLOCK_HASH_MISMATCH = "BLOCK_HASH_MISMATCH"
    PREV_HASH_MISMATCH = "PREV_HASH_MISMATCH"
    RECORD_HASH_MISMATCH = "RECORD_HASH_MISMATCH"


@dataclass(frozen=True)
class ValidationIssue:
    block_index: int
    code: IssueCode
    message: str
    expected: str | None = None
    actual: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    # цепочка валидна, если нарушений нет
    @property
    def is_valid(self) -> bool:
        return not self.issues

    # точка разрыва: первое нарушение, если оно есть
    @property
    def first_issue(self) -> ValidationIssue | None:
        return self.issues[0] if self.issues else None

    # короткий текст для людей: первое нарушение и сколько ещё найдено
    def summary(self) -> str:
        first = self.first_issue
        if first is None:
            return "Цепочка валидна"
        text = f"Цепочка повреждена. {first.message}"
        others = len(self.issues) - 1
        if others:
            text += f" (найдено ещё нарушений: {others})"
        return text


# проверяет блоки и собирает все нарушения, а не останавливается на первом
def validate_blocks(
    blocks: Sequence[Block], hash_service: IHashService
) -> ValidationReport:
    if not blocks:
        issue = ValidationIssue(0, IssueCode.EMPTY_CHAIN, "в цепочке нет блоков")
        return ValidationReport((issue,))
    issues: list[ValidationIssue] = []
    for position, block in enumerate(blocks):
        previous = blocks[position - 1] if position > 0 else None
        issues.extend(_check_block(position, block, previous, hash_service))
    return ValidationReport(tuple(issues))


# нарушения одного блока: номер, genesis, хеш блока, хеши записей и ссылка на предыдущий
def _check_block(
    position: int,
    block: Block,
    previous: Block | None,
    hash_service: IHashService,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if block.index != position:
        issues.append(
            ValidationIssue(
                position,
                IssueCode.INDEX_MISMATCH,
                f"Блок {position}: в блоке указан номер {block.index}",
                str(position),
                str(block.index),
            )
        )
    if previous is None and block.prev_hash != GENESIS_PREV_HASH:
        issues.append(
            ValidationIssue(
                position,
                IssueCode.GENESIS_INVALID,
                f"Блок {position}: у genesis prevHash должен состоять из нулей",
                GENESIS_PREV_HASH,
                block.prev_hash,
            )
        )
    expected_hash = block.compute_hash(hash_service)
    if block.hash != expected_hash:
        issues.append(
            ValidationIssue(
                position,
                IssueCode.BLOCK_HASH_MISMATCH,
                f"Блок {position}: хеш блока не совпадает с пересчитанным",
                expected_hash,
                block.hash,
            )
        )
    for record in block.records:
        record_hash = record.compute_hash(hash_service)
        if record.record_hash != record_hash:
            issues.append(
                ValidationIssue(
                    position,
                    IssueCode.RECORD_HASH_MISMATCH,
                    f"Блок {position}: запись {record.record_id} изменена, "
                    "хеш записи не совпадает с пересчитанным",
                    record_hash,
                    record.record_hash,
                )
            )
    if previous is not None and block.prev_hash != previous.hash:
        issues.append(
            ValidationIssue(
                position,
                IssueCode.PREV_HASH_MISMATCH,
                f"Блок {position}: prevHash не совпадает с хешем блока {position - 1}",
                previous.hash,
                block.prev_hash,
            )
        )
    return issues
