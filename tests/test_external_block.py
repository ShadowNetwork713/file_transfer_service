import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.core.block import Block
from app.core.blockchain import Blockchain, RejectedBlockError
from app.core.hashing import Blake2bHashService
from app.core.record import Record
from app.core.storage import JsonChainRepository

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"


class ExternalBlockTest(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.data_dir.cleanup)
        self.hash_service = Blake2bHashService()
        self.first_path = Path(self.data_dir.name) / "first" / "chain.json"
        self.second_path = Path(self.data_dir.name) / "second" / "chain.json"
        self.first = self.open_chain(self.first_path)
        self.second = self.open_chain(self.second_path)

    def open_chain(self, path: Path) -> Blockchain:
        return Blockchain(self.hash_service, repository=JsonChainRepository(path))

    def make_block(self) -> Block:
        record = Record.create(DOCUMENT_ID, "a" * 64, self.hash_service)
        return self.first.add_block([record])

    def assert_rejected(self, block: Block, expected_code: str) -> None:
        original_file = self.second_path.read_bytes()
        with self.assertRaises(RejectedBlockError) as caught:
            self.second.append_external_block(block)
        self.assertEqual(caught.exception.code, expected_code)
        self.assertEqual(self.second_path.read_bytes(), original_file)
        self.assertTrue(self.second.validate_chain())

    def test_two_repositories_share_genesis_but_not_file(self):
        self.assertEqual(self.first.last_block.hash, self.second.last_block.hash)
        self.make_block()
        self.assertEqual(len(self.first), 2)
        self.assertEqual(len(self.second), 1)

    def test_valid_block_survives_reception_and_restart(self):
        block = self.make_block()
        self.assertTrue(self.second.append_external_block(block))
        self.assertEqual(self.second.last_block, block)
        self.assertEqual(self.open_chain(self.second_path).last_block, block)
        self.assertTrue(self.second.validate_chain())

    def test_repeated_identical_block_does_not_write_again(self):
        block = self.make_block()
        self.second.append_external_block(block)
        original_file = self.second_path.read_bytes()
        self.assertFalse(self.second.append_external_block(block))
        self.assertEqual(self.second_path.read_bytes(), original_file)

    def test_changed_block_hash_is_rejected(self):
        block = self.make_block()
        self.assert_rejected(replace(block, hash="f" * 64), "BLOCK_HASH_MISMATCH")

    def test_changed_record_is_rejected(self):
        block = self.make_block()
        changed_record = replace(block.records[0], file_hash="b" * 64)
        self.assert_rejected(
            replace(block, records=[changed_record]), "RECORD_HASH_MISMATCH"
        )

    def test_wrong_previous_hash_is_rejected(self):
        block = self.make_block()
        self.assert_rejected(replace(block, prev_hash="f" * 64), "PREV_HASH_MISMATCH")

    def test_gap_is_rejected(self):
        block = self.make_block()
        self.assert_rejected(replace(block, index=2), "INDEX_MISMATCH")

    def test_conflicting_block_is_rejected(self):
        block = self.make_block()
        self.second.append_external_block(block)
        competing_chain = Blockchain(self.hash_service)
        conflict = competing_chain.add_block(
            [Record.create(DOCUMENT_ID, "b" * 64, self.hash_service)]
        )
        self.assert_rejected(conflict, "BLOCK_CONFLICT")

    def test_failed_save_keeps_chain_in_memory_and_on_disk(self):
        block = self.make_block()
        original_file = self.second_path.read_bytes()
        with patch.object(self.second._repository, "save_chain", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.second.append_external_block(block)
        self.assertEqual(len(self.second), 1)
        self.assertEqual(self.second_path.read_bytes(), original_file)

    def test_blocked_chain_cannot_accept_block(self):
        block = self.make_block()
        self.second.blocks[0].hash = "f" * 64
        with self.assertRaises(RejectedBlockError) as caught:
            self.second.append_external_block(block)
        self.assertEqual(caught.exception.code, "CHAIN_INVALID")
        self.assertEqual(len(self.open_chain(self.second_path)), 1)


if __name__ == "__main__":
    unittest.main()
