import json
import tempfile
import unittest
from pathlib import Path

from app.core.blockchain import Blockchain, InvalidChainError
from app.core.hashing import Blake2bHashService
from app.core.record import Record
from app.core.storage import ChainStorageError, JsonChainRepository

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"


class JsonChainRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "data" / "chain.json"
        self.hash_service = Blake2bHashService()
        self.repository = JsonChainRepository(self.path)

    def make_record(self, char: str = "a") -> Record:
        return Record.create(DOCUMENT_ID, char * 64, self.hash_service)

    def open_chain(self) -> Blockchain:
        return Blockchain(self.hash_service, repository=self.repository)

    # без файла создаётся genesis и сразу сохраняется
    def test_missing_file_creates_genesis(self):
        chain = self.open_chain()
        self.assertEqual(len(chain), 1)
        self.assertTrue(self.path.exists())
        self.assertEqual(len(self.repository.load_chain()), 1)

    # после перезапуска цепочка поднимается из файла и валидна
    def test_chain_survives_restart(self):
        chain = self.open_chain()
        chain.add_block([self.make_record("a")])
        chain.add_block([self.make_record("b")])
        restored = self.open_chain()
        self.assertEqual(restored.blocks, chain.blocks)
        self.assertTrue(restored.validate_chain())
        self.assertFalse(restored.is_blocked)

    # цепочка продолжается после перезапуска
    def test_chain_continues_after_restart(self):
        self.open_chain().add_block([self.make_record("a")])
        restored = self.open_chain()
        block = restored.add_block([self.make_record("b")])
        self.assertEqual(block.index, 2)
        self.assertEqual(len(self.open_chain()), 3)

    # формат файла: версия и список блоков в camelCase
    def test_file_format(self):
        chain = self.open_chain()
        chain.add_block([self.make_record()])
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["blocks"]), 2)
        self.assertEqual(
            set(data["blocks"][1]),
            {"index", "timestamp", "prevHash", "records", "hash"},
        )

    # после сохранения во временный файл ничего лишнего не остаётся
    def test_no_temp_files_left(self):
        chain = self.open_chain()
        chain.add_block([self.make_record()])
        names = sorted(item.name for item in self.path.parent.iterdir())
        self.assertEqual(names, ["chain.json"])

    # ручная правка файла обнаруживается, добавление блоков блокируется, ошибка в логе
    def test_manual_edit_blocks_chain(self):
        self.open_chain().add_block([self.make_record()])
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["blocks"][1]["records"][0]["fileHash"] = "f" * 64
        self.path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertLogs("app.core.blockchain", level="ERROR"):
            chain = self.open_chain()
        self.assertTrue(chain.is_blocked)
        self.assertFalse(chain.validate_chain())
        with self.assertRaises(InvalidChainError):
            chain.add_block([self.make_record("b")])

    # нечитаемый файл блокирует цепочку и остаётся нетронутым
    def test_unreadable_file_blocks_chain_and_is_kept(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{ это не json", encoding="utf-8")
        with self.assertLogs("app.core.blockchain", level="ERROR"):
            chain = self.open_chain()
        self.assertTrue(chain.is_blocked)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{ это не json")
        with self.assertRaises(InvalidChainError):
            chain.add_block([self.make_record()])

    # файл с неверной структурой даёт ошибку хранилища
    def test_wrong_structure_raises_storage_error(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"blocks": [{"index": 0}]}', encoding="utf-8")
        with self.assertRaises(ChainStorageError):
            self.repository.load_chain()

    # неудачное сохранение не портит прежний файл
    def test_failed_save_keeps_previous_file(self):
        chain = self.open_chain()
        before = self.path.read_text(encoding="utf-8")
        broken_block = chain.last_block.to_dict()
        broken_block["hash"] = object()
        with self.assertRaises(TypeError):
            self.repository.save_chain([chain.last_block, _BrokenBlock(broken_block)])
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertEqual(
            sorted(item.name for item in self.path.parent.iterdir()), ["chain.json"]
        )


class _BrokenBlock:
    # блок, который нельзя превратить в json
    def __init__(self, data):
        self.data = data

    # отдаёт словарь с объектом, который json не умеет писать
    def to_dict(self):
        return self.data


if __name__ == "__main__":
    unittest.main()
