import unittest

from app.core.block import GENESIS_PREV_HASH
from app.core.blockchain import GENESIS_TIMESTAMP, Blockchain, InvalidChainError
from app.core.hashing import Blake2bHashService
from app.core.record import Record

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"


class BlockchainTest(unittest.TestCase):
    def setUp(self):
        self.hash_service = Blake2bHashService()
        self.chain = Blockchain(self.hash_service)

    def make_record(self, char: str = "a") -> Record:
        return Record.create(DOCUMENT_ID, char * 64, self.hash_service)

    # новая цепочка состоит из одного genesis-блока
    def test_new_chain_has_genesis(self):
        genesis = self.chain.last_block
        self.assertEqual(len(self.chain), 1)
        self.assertEqual(genesis.index, 0)
        self.assertEqual(genesis.prev_hash, GENESIS_PREV_HASH)
        self.assertEqual(genesis.timestamp, GENESIS_TIMESTAMP)
        self.assertEqual(genesis.records, [])
        self.assertTrue(self.chain.validate_chain())

    # genesis одинаковый в разных экземплярах цепочки
    def test_genesis_is_deterministic(self):
        other = Blockchain(self.hash_service)
        self.assertEqual(other.last_block.hash, self.chain.last_block.hash)

    # новый блок ссылается на предыдущий и получает следующий номер
    def test_add_block_links_to_previous(self):
        first = self.chain.add_block([self.make_record("a")])
        second = self.chain.add_block([self.make_record("b"), self.make_record("c")])
        self.assertEqual((first.index, second.index), (1, 2))
        self.assertEqual(first.prev_hash, self.chain.blocks[0].hash)
        self.assertEqual(second.prev_hash, first.hash)
        self.assertEqual(len(self.chain), 3)

    # целая цепочка валидна
    def test_intact_chain_is_valid(self):
        for char in "abcde":
            self.chain.add_block([self.make_record(char)])
        self.assertTrue(self.chain.validate_chain())

    # блок без записей добавить нельзя
    def test_empty_block_is_rejected(self):
        with self.assertRaises(ValueError):
            self.chain.add_block([])
        self.assertEqual(len(self.chain), 1)

    # в повреждённую цепочку блоки не добавляются
    def test_add_block_is_blocked_on_broken_chain(self):
        self.chain.add_block([self.make_record()])
        self.chain.blocks[1].records[0] = self.make_record("f")
        self.assertFalse(self.chain.validate_chain())
        with self.assertRaises(InvalidChainError):
            self.chain.add_block([self.make_record("d")])
        self.assertEqual(len(self.chain), 2)

    # цепочку можно собрать из готовых блоков
    def test_chain_from_existing_blocks(self):
        self.chain.add_block([self.make_record()])
        restored = Blockchain(self.hash_service, self.chain.blocks)
        self.assertEqual(restored.blocks, self.chain.blocks)
        self.assertTrue(restored.validate_chain())


if __name__ == "__main__":
    unittest.main()
