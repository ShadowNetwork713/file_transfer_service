import io
import unittest

from app.core.blockchain import Blockchain
from app.core.hashing import Blake2bHashService
from app.core.service import BlockchainService, FileCheckStatus

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_DOCUMENT_ID = "33333333-3333-4333-8333-333333333333"
CONTENT = b"contract.pdf content"


class VerifyFileTest(unittest.TestCase):
    def setUp(self):
        self.hash_service = Blake2bHashService()
        self.chain = Blockchain(self.hash_service)
        self.service = BlockchainService(self.chain, self.hash_service)
        self.file_hash = self.hash_service.hash_bytes(CONTENT)
        self.service.register_document(DOCUMENT_ID, self.file_hash)

    # неизменённый файл подтверждается
    def test_unchanged_file_is_valid(self):
        result = self.service.verify_file(DOCUMENT_ID, io.BytesIO(CONTENT))
        self.assertEqual(result.status, FileCheckStatus.VALID)
        self.assertEqual(result.current_hash, self.file_hash)
        self.assertEqual(result.registered_hash, self.file_hash)
        self.assertEqual(result.block_index, 1)
        self.assertIn("подтверждена", result.message)

    # изменённый на один байт файл не подтверждается
    def test_changed_file_is_invalid(self):
        changed = CONTENT[:-1] + b"X"
        result = self.service.verify_file(DOCUMENT_ID, io.BytesIO(changed))
        self.assertEqual(result.status, FileCheckStatus.INVALID)
        self.assertNotEqual(result.current_hash, result.registered_hash)
        self.assertEqual(result.registered_hash, self.file_hash)
        self.assertEqual(result.block_index, 1)
        self.assertIn("не подтверждена", result.message)

    # пустой файл тоже сверяется
    def test_empty_file_is_invalid(self):
        result = self.service.verify_file(DOCUMENT_ID, io.BytesIO(b""))
        self.assertEqual(result.status, FileCheckStatus.INVALID)

    # документа нет в цепочке
    def test_unknown_document_is_not_found(self):
        result = self.service.verify_file(OTHER_DOCUMENT_ID, io.BytesIO(CONTENT))
        self.assertEqual(result.status, FileCheckStatus.NOT_FOUND)
        self.assertIsNone(result.registered_hash)
        self.assertIsNone(result.block_index)

    # некорректный идентификатор это просто ненайденный документ
    def test_bad_document_id_is_not_found(self):
        result = self.service.verify_file("not-a-uuid", io.BytesIO(CONTENT))
        self.assertEqual(result.status, FileCheckStatus.NOT_FOUND)

    # на повреждённой цепочке файл не подтверждается и называется блок
    def test_broken_chain_does_not_confirm_file(self):
        self.chain.blocks[1].hash = "e" * 64
        result = self.service.verify_file(DOCUMENT_ID, io.BytesIO(CONTENT))
        self.assertEqual(result.status, FileCheckStatus.CHAIN_INVALID)
        self.assertIn("Блок 1", result.message)

    # при нескольких версиях документа сверка идёт с последней
    def test_latest_registration_is_used(self):
        new_content = b"contract v2"
        new_hash = self.hash_service.hash_bytes(new_content)
        self.service.register_document(DOCUMENT_ID, new_hash)
        latest = self.service.verify_file(DOCUMENT_ID, io.BytesIO(new_content))
        old = self.service.verify_file(DOCUMENT_ID, io.BytesIO(CONTENT))
        self.assertEqual(latest.status, FileCheckStatus.VALID)
        self.assertEqual(latest.block_index, 2)
        self.assertEqual(old.status, FileCheckStatus.INVALID)

    # поиск записей документа в порядке регистрации
    def test_find_records(self):
        self.service.register_document(DOCUMENT_ID, self.hash_service.hash_text("v2"))
        found = self.chain.find_records(DOCUMENT_ID)
        self.assertEqual([index for _, index in found], [1, 2])
        self.assertEqual(self.chain.find_records(OTHER_DOCUMENT_ID), [])


if __name__ == "__main__":
    unittest.main()
