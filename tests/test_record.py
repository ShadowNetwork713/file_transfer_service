import dataclasses
import unittest
import uuid

from app.core.hashing import Blake2bHashService, is_valid_hash
from app.core.record import Record

FILE_HASH = "a" * 64
OTHER_HASH = "b" * 64


def make_record(**overrides) -> Record:
    params = {
        "document_id": "11111111-1111-4111-8111-111111111111",
        "file_hash": FILE_HASH,
        "record_id": "22222222-2222-4222-8222-222222222222",
        "timestamp": 1_700_000_000_000,
    }
    params.update(overrides)
    return Record.create(hash_service=Blake2bHashService(), **params)


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.hash_service = Blake2bHashService()

    # одинаковые данные дают одинаковый хеш
    def test_same_data_gives_same_hash(self):
        self.assertEqual(make_record().record_hash, make_record().record_hash)

    # изменение любого поля меняет хеш
    def test_any_field_change_changes_hash(self):
        original = make_record()
        changes = {
            "record_id": str(uuid.uuid4()),
            "document_id": str(uuid.uuid4()),
            "file_hash": OTHER_HASH,
            "timestamp": original.timestamp + 1,
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                changed = dataclasses.replace(original, **{field: value})
                self.assertNotEqual(
                    changed.compute_hash(self.hash_service), original.record_hash
                )
                self.assertFalse(changed.verify(self.hash_service))

    # хеш записи формата hex 64 и проходит проверку
    def test_created_record_is_valid(self):
        record = make_record()
        self.assertTrue(is_valid_hash(record.record_hash))
        self.assertTrue(record.verify(self.hash_service))

    # канонический json: ключи по алфавиту, без пробелов и без recordHash
    def test_canonical_json(self):
        self.assertEqual(
            make_record().to_canonical_json(),
            '{"documentId":"11111111-1111-4111-8111-111111111111",'
            f'"fileHash":"{FILE_HASH}",'
            '"recordId":"22222222-2222-4222-8222-222222222222",'
            '"timestamp":1700000000000}',
        )

    # в записи только хеш и идентификаторы, без имени файла и персональных данных
    def test_dict_has_only_ids_and_hashes(self):
        self.assertEqual(
            set(make_record().to_dict()),
            {"recordId", "documentId", "fileHash", "timestamp", "recordHash"},
        )

    # запись переживает превращение в словарь и обратно
    def test_dict_roundtrip(self):
        record = make_record()
        self.assertEqual(Record.from_dict(record.to_dict()), record)

    # без явных id и времени они подставляются сами
    def test_defaults_are_generated(self):
        record = Record.create(
            "11111111-1111-4111-8111-111111111111", FILE_HASH, self.hash_service
        )
        self.assertTrue(record.verify(self.hash_service))
        self.assertGreater(record.timestamp, 0)
        self.assertEqual(str(uuid.UUID(record.record_id)), record.record_id)

    # некорректные идентификаторы и хеш отклоняются
    def test_invalid_input_is_rejected(self):
        bad_values = {
            "document_id": "not-a-uuid",
            "record_id": "22222222-2222-4222-8222-22222222222G",
            "file_hash": "xyz",
        }
        for field, value in bad_values.items():
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    make_record(**{field: value})
        with self.assertRaises(ValueError):
            make_record(document_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa".upper())


if __name__ == "__main__":
    unittest.main()
