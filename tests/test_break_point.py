import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from app.core.blockchain import Blockchain, InvalidChainError
from app.core.hashing import Blake2bHashService
from app.core.record import Record
from app.core.storage import JsonChainRepository
from app.core.validation import IssueCode

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"


class BreakPointTest(unittest.TestCase):
    def setUp(self):
        self.hash_service = Blake2bHashService()
        self.chain = Blockchain(self.hash_service)
        for number in range(4):
            record = Record.create(DOCUMENT_ID, f"{number:x}" * 64, self.hash_service)
            self.chain.add_block([record])

    # целая цепочка: точки разрыва нет
    def test_intact_chain_has_no_break(self):
        self.assertIsNone(self.chain.find_break())
        self.assertIsNone(self.chain.validate_report().first_issue)
        self.assertEqual(self.chain.validate_report().summary(), "Цепочка валидна")

    # подмена записи: называется блок и причина
    def test_record_tampering_names_block_and_reason(self):
        block = self.chain.blocks[2]
        block.records[0] = dataclasses.replace(block.records[0], file_hash="e" * 64)
        issue = self.chain.find_break()
        self.assertEqual(issue.block_index, 2)
        self.assertEqual(issue.code, IssueCode.RECORD_HASH_MISMATCH)
        self.assertIn("Блок 2", issue.message)
        self.assertIn("запись", issue.message)

    # подмена prevHash: называется блок и причина
    def test_prev_hash_tampering_names_block_and_reason(self):
        forged = dataclasses.replace(self.chain.blocks[3], prev_hash="d" * 64)
        forged.hash = forged.compute_hash(self.hash_service)
        blocks = list(self.chain.blocks)
        blocks[3] = forged
        chain = self.assert_blocked_on_load(blocks)
        issue = chain.find_break()
        self.assertEqual(
            (issue.block_index, issue.code), (3, IssueCode.PREV_HASH_MISMATCH)
        )
        self.assertIn("prevHash", issue.message)

    # сборка цепочки из подменённых блоков пишет в лог блок и причину
    def assert_blocked_on_load(self, blocks):
        with self.assertLogs("app.core.blockchain", level="ERROR") as logs:
            chain = Blockchain(self.hash_service, blocks)
        self.assertIn("Блок 3", logs.output[0])
        self.assertTrue(chain.is_blocked)
        return chain

    # сводка показывает первое нарушение и число остальных
    def test_summary_counts_other_issues(self):
        self.chain.blocks[1].hash = "e" * 64
        report = self.chain.validate_report()
        self.assertEqual(len(report.issues), 2)
        self.assertIn("Блок 1", report.summary())
        self.assertIn("ещё нарушений: 1", report.summary())

    # добавление в повреждённую цепочку отказывает с указанием блока
    def test_add_block_error_names_block(self):
        self.chain.blocks[2].hash = "e" * 64
        record = Record.create(DOCUMENT_ID, "f" * 64, self.hash_service)
        with self.assertRaises(InvalidChainError) as raised:
            self.chain.add_block([record])
        self.assertIn("Блок 2", str(raised.exception))

    # при загрузке файла в лог попадает блок и причина
    def test_load_from_file_logs_break_point(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "chain.json"
            repository = JsonChainRepository(path)
            repository.save_chain(self.chain.blocks)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["blocks"][3]["records"][0]["fileHash"] = "e" * 64
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertLogs("app.core.blockchain", level="ERROR") as logs:
                chain = Blockchain(self.hash_service, repository=repository)
        self.assertIn("Блок 3", logs.output[0])
        self.assertIn("запись", logs.output[0])
        self.assertEqual(chain.find_break().block_index, 3)

    # нечитаемый файл блокирует цепочку с понятной причиной
    def test_unreadable_file_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "chain.json"
            path.write_text("{ не json", encoding="utf-8")
            with self.assertLogs("app.core.blockchain", level="ERROR"):
                chain = Blockchain(
                    self.hash_service, repository=JsonChainRepository(path)
                )
        record = Record.create(DOCUMENT_ID, "f" * 64, self.hash_service)
        with self.assertRaises(InvalidChainError) as raised:
            chain.add_block([record])
        self.assertIn("прочитать", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
