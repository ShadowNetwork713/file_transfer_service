import json
import tempfile
import unittest
from pathlib import Path

from app.core.blockchain import Blockchain
from app.core.hashing import Blake2bHashService
from app.core.service import BlockchainService, RegistrationStatus
from app.core.storage import JsonChainRepository

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_DOCUMENT_ID = "33333333-3333-4333-8333-333333333333"
FILE_HASH = "a" * 64


class BlockchainServiceTest(unittest.TestCase):
    def setUp(self):
        self.hash_service = Blake2bHashService()
        self.chain = Blockchain(self.hash_service)
        self.service = BlockchainService(self.chain, self.hash_service)

    # регистрация кладёт запись в блок и возвращает хеш записи как идентификатор
    def test_register_document_confirms_in_block(self):
        result = self.service.register_document(DOCUMENT_ID, FILE_HASH)
        self.assertEqual(result.status, RegistrationStatus.CONFIRMED)
        self.assertEqual(result.block_index, 1)
        self.assertIsNone(result.error)
        stored = self.chain.blocks[1].records[0]
        self.assertEqual(result.tx_id, stored.record_hash)
        self.assertEqual(stored.document_id, DOCUMENT_ID)
        self.assertEqual(stored.file_hash, FILE_HASH)

    # разные документы попадают в разные блоки
    def test_documents_go_to_separate_blocks(self):
        first = self.service.register_document(DOCUMENT_ID, FILE_HASH)
        second = self.service.register_document(OTHER_DOCUMENT_ID, FILE_HASH)
        self.assertEqual((first.block_index, second.block_index), (1, 2))
        self.assertNotEqual(first.tx_id, second.tx_id)

    # повтор той же регистрации не создаёт новый блок
    def test_repeated_registration_is_idempotent(self):
        first = self.service.register_document(DOCUMENT_ID, FILE_HASH)
        second = self.service.register_document(DOCUMENT_ID, FILE_HASH)
        self.assertEqual(second, first)
        self.assertEqual(len(self.chain), 2)

    # некорректные данные это ошибка вызова, а не FAILED
    def test_invalid_input_raises(self):
        with self.assertRaises(ValueError):
            self.service.register_document("not-a-uuid", FILE_HASH)
        with self.assertRaises(ValueError):
            self.service.register_document(DOCUMENT_ID, "xyz")

    # проверка цепочки проходит на целой цепочке
    def test_validate_chain(self):
        self.service.register_document(DOCUMENT_ID, FILE_HASH)
        self.assertTrue(self.service.validate_chain())

    # на повреждённой цепочке регистрация возвращает FAILED, а не падает
    def test_broken_chain_gives_failed(self):
        self.service.register_document(DOCUMENT_ID, FILE_HASH)
        self.chain.blocks[1].timestamp += 1
        self.assertFalse(self.service.validate_chain())
        with self.assertLogs("app.core.service", level="ERROR"):
            result = self.service.register_document(OTHER_DOCUMENT_ID, FILE_HASH)
        self.assertEqual(result.status, RegistrationStatus.FAILED)
        self.assertIsNone(result.tx_id)
        self.assertTrue(result.error)
        self.assertEqual(len(self.chain), 2)

    # сбой записи на диск даёт FAILED, повтор после починки проходит
    def test_storage_failure_can_be_retried(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "chain.json"
            repository = JsonChainRepository(path)
            chain = Blockchain(self.hash_service, repository=repository)
            service = BlockchainService(chain, self.hash_service)
            path.unlink()
            path.mkdir()
            with self.assertLogs("app.core.service", level="ERROR"):
                failed = service.register_document(DOCUMENT_ID, FILE_HASH)
            self.assertEqual(failed.status, RegistrationStatus.FAILED)
            self.assertEqual(len(chain), 1)
            path.rmdir()
            retried = service.register_document(DOCUMENT_ID, FILE_HASH)
            self.assertEqual(retried.status, RegistrationStatus.CONFIRMED)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["blocks"]), 2)


if __name__ == "__main__":
    unittest.main()
