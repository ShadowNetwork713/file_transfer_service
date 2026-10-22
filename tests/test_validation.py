import dataclasses
import unittest

from app.core.block import Block
from app.core.blockchain import Blockchain
from app.core.hashing import Blake2bHashService
from app.core.record import Record
from app.core.validation import IssueCode, validate_blocks

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
BLOCK_COUNT = 4


class ValidationReportTest(unittest.TestCase):
    def setUp(self):
        self.hash_service = Blake2bHashService()
        self.chain = Blockchain(self.hash_service)
        for number in range(BLOCK_COUNT):
            record = Record.create(DOCUMENT_ID, f"{number:x}" * 64, self.hash_service)
            self.chain.add_block([record])

    # копии блоков, чтобы подмены не влияли на исходную цепочку
    def fresh_blocks(self) -> list[Block]:
        return [Block.from_dict(block.to_dict()) for block in self.chain.blocks]

    # коды нарушений в отчёте
    def codes(self, blocks: list[Block]) -> list[tuple[int, IssueCode]]:
        report = validate_blocks(blocks, self.hash_service)
        return [(issue.block_index, issue.code) for issue in report.issues]

    # целая цепочка даёт пустой отчёт
    def test_intact_chain_gives_empty_report(self):
        report = self.chain.validate_report()
        self.assertTrue(report.is_valid)
        self.assertEqual(report.issues, ())
        self.assertTrue(self.chain.validate_chain())

    # подмена записи: хеш записи не сходится в нужном блоке
    def test_record_tampering(self):
        blocks = self.fresh_blocks()
        blocks[2].records[0] = dataclasses.replace(
            blocks[2].records[0], file_hash="e" * 64
        )
        self.assertEqual(self.codes(blocks), [(2, IssueCode.RECORD_HASH_MISMATCH)])

    # подмена хеша блока: не сходится и сам блок, и ссылка следующего
    def test_block_hash_tampering(self):
        blocks = self.fresh_blocks()
        blocks[1].hash = "e" * 64
        self.assertEqual(
            self.codes(blocks),
            [(1, IssueCode.BLOCK_HASH_MISMATCH), (2, IssueCode.PREV_HASH_MISMATCH)],
        )

    # подмена prevHash с пересчитанным хешем блока: рвётся только ссылка
    def test_prev_hash_tampering(self):
        blocks = self.fresh_blocks()
        forged = dataclasses.replace(blocks[BLOCK_COUNT], prev_hash="d" * 64)
        forged.hash = forged.compute_hash(self.hash_service)
        blocks[BLOCK_COUNT] = forged
        self.assertEqual(
            self.codes(blocks), [(BLOCK_COUNT, IssueCode.PREV_HASH_MISMATCH)]
        )

    # неверный номер блока
    def test_index_mismatch(self):
        blocks = self.fresh_blocks()
        forged = dataclasses.replace(blocks[2], index=7)
        forged.hash = forged.compute_hash(self.hash_service)
        blocks[2] = forged
        codes = self.codes(blocks)
        self.assertIn((2, IssueCode.INDEX_MISMATCH), codes)

    # genesis с ненулевым prevHash
    def test_genesis_invalid(self):
        blocks = self.fresh_blocks()
        forged = dataclasses.replace(blocks[0], prev_hash="c" * 64)
        forged.hash = forged.compute_hash(self.hash_service)
        blocks[0] = forged
        codes = self.codes(blocks)
        self.assertIn((0, IssueCode.GENESIS_INVALID), codes)
        self.assertIn((1, IssueCode.PREV_HASH_MISMATCH), codes)

    # пустой список блоков
    def test_empty_chain(self):
        report = validate_blocks([], self.hash_service)
        self.assertFalse(report.is_valid)
        self.assertEqual(report.issues[0].code, IssueCode.EMPTY_CHAIN)

    # несколько нарушений попадают в отчёт все сразу
    def test_several_issues_are_all_reported(self):
        blocks = self.fresh_blocks()
        blocks[1].records[0] = dataclasses.replace(
            blocks[1].records[0], file_hash="e" * 64
        )
        blocks[BLOCK_COUNT].hash = "e" * 64
        self.assertEqual(
            self.codes(blocks),
            [
                (1, IssueCode.RECORD_HASH_MISMATCH),
                (BLOCK_COUNT, IssueCode.BLOCK_HASH_MISMATCH),
            ],
        )

    # в нарушении есть сообщение с номером блока, ожидаемое и фактическое значение
    def test_issue_details(self):
        blocks = self.fresh_blocks()
        blocks[2].hash = "e" * 64
        issue = validate_blocks(blocks, self.hash_service).issues[0]
        self.assertIn("Блок 2", issue.message)
        self.assertEqual(issue.actual, "e" * 64)
        self.assertEqual(issue.expected, blocks[2].compute_hash(self.hash_service))

    # булева проверка цепочки согласована с отчётом
    def test_validate_chain_matches_report(self):
        self.chain.blocks[1].hash = "e" * 64
        self.assertFalse(self.chain.validate_report().is_valid)
        self.assertFalse(self.chain.validate_chain())


if __name__ == "__main__":
    unittest.main()
