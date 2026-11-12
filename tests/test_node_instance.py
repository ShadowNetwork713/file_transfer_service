import tempfile
import unittest
from pathlib import Path

from app.core.blockchain import Blockchain
from app.core.hashing import Blake2bHashService
from app.core.storage import JsonChainRepository
from app.network.instance import DataDirectoryInUseError, lock_data_directory


class NodeInstanceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.first_dir = Path(self.temp_dir.name) / "first"
        self.second_dir = Path(self.temp_dir.name) / "second"

    def test_two_nodes_have_independent_storage(self):
        with lock_data_directory(self.first_dir) as first_path:
            with lock_data_directory(self.second_dir) as second_path:
                self.assertNotEqual(first_path, second_path)
                first_chain = Blockchain(
                    Blake2bHashService(),
                    repository=JsonChainRepository(first_path / "chain.json"),
                )
                second_chain = Blockchain(
                    Blake2bHashService(),
                    repository=JsonChainRepository(second_path / "chain.json"),
                )
                self.assertEqual(first_chain.last_block.hash, second_chain.last_block.hash)
                self.assertNotEqual(
                    first_path / "chain.json", second_path / "chain.json"
                )

    def test_same_directory_is_rejected_until_first_node_stops(self):
        with lock_data_directory(self.first_dir):
            with self.assertRaises(DataDirectoryInUseError):
                with lock_data_directory(self.first_dir):
                    self.fail("Вторая нода открыла занятый каталог")
        with lock_data_directory(self.first_dir):
            self.assertTrue(self.first_dir.is_dir())

    def test_file_cannot_be_used_as_data_directory(self):
        data_file = Path(self.temp_dir.name) / "file.txt"
        data_file.write_text("data", encoding="utf-8")
        with self.assertRaises(ValueError):
            with lock_data_directory(data_file):
                self.fail("Файл принят как каталог данных")


if __name__ == "__main__":
    unittest.main()
