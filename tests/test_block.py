import dataclasses
import unittest

from app.core.block import GENESIS_PREV_HASH, Block
from app.core.hashing import Blake2bHashService, is_valid_hash
from app.core.record import Record

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"


class BlockTest(unittest.TestCase):
    def setUp(self):
        self.hash_service = Blake2bHashService()
        self.records = [
            Record.create(
                DOCUMENT_ID,
                char * 64,
                self.hash_service,
                record_id=f"{number:08d}-0000-4000-8000-000000000000",
                timestamp=1_700_000_000_000 + number,
            )
            for number, char in enumerate("abc", start=1)
        ]
        self.block = Block.create(
            1,
            GENESIS_PREV_HASH,
            self.records,
            self.hash_service,
            timestamp=1_700_000_001_000,
        )

    # хеш блока пересчитывается и совпадает
    def test_hash_recomputes(self):
        self.assertTrue(is_valid_hash(self.block.hash))
        self.assertEqual(self.block.compute_hash(self.hash_service), self.block.hash)
        self.assertTrue(self.block.verify(self.hash_service))

    # одинаковые данные дают одинаковый хеш блока
    def test_same_data_gives_same_hash(self):
        twin = Block.create(
            1,
            GENESIS_PREV_HASH,
            self.records,
            self.hash_service,
            timestamp=self.block.timestamp,
        )
        self.assertEqual(twin.hash, self.block.hash)

    # изменение любого поля заголовка меняет хеш блока
    def test_header_change_changes_hash(self):
        changes = {
            "index": 2,
            "timestamp": self.block.timestamp + 1,
            "prev_hash": "f" * 64,
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                changed = dataclasses.replace(self.block, **{field: value})
                self.assertNotEqual(
                    changed.compute_hash(self.hash_service), self.block.hash
                )
                self.assertFalse(changed.verify(self.hash_service))

    # другой набор или порядок записей меняет хеш блока
    def test_records_change_changes_hash(self):
        variants = {
            "fewer": self.records[:-1],
            "reversed": list(reversed(self.records)),
        }
        for name, records in variants.items():
            with self.subTest(variant=name):
                changed = dataclasses.replace(self.block, records=records)
                self.assertNotEqual(
                    changed.compute_hash(self.hash_service), self.block.hash
                )

    # подмена содержимого записи ломает проверку блока
    def test_record_tampering_is_detected(self):
        forged = dataclasses.replace(self.records[0], file_hash="e" * 64)
        self.block.records[0] = forged
        self.assertFalse(self.block.verify(self.hash_service))

    # блок можно создать без записей, например genesis
    def test_empty_block_is_valid(self):
        block = Block.create(0, GENESIS_PREV_HASH, [], self.hash_service, timestamp=0)
        self.assertTrue(block.verify(self.hash_service))

    # блок переживает превращение в словарь и обратно
    def test_dict_roundtrip(self):
        restored = Block.from_dict(self.block.to_dict())
        self.assertEqual(restored, self.block)
        self.assertTrue(restored.verify(self.hash_service))


if __name__ == "__main__":
    unittest.main()
