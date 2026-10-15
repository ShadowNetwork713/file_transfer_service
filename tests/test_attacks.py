import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from app.core.block import Block
from app.core.blockchain import Blockchain
from app.core.hashing import Blake2bHashService
from app.core.record import Record
from app.core.storage import JsonChainRepository

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
BLOCK_COUNT = 5


class TamperingTest(unittest.TestCase):
    def setUp(self):
        self.hash_service = Blake2bHashService()
        self.chain = Blockchain(self.hash_service)
        for number in range(BLOCK_COUNT):
            record = Record.create(DOCUMENT_ID, f"{number:x}" * 64, self.hash_service)
            self.chain.add_block([record])

    # копии блоков, чтобы подмены в одном тесте не влияли на другие
    def fresh_blocks(self) -> list[Block]:
        return [Block.from_dict(block.to_dict()) for block in self.chain.blocks]

    # цепочка из подменённых блоков, при сборке она должна залогировать ошибку
    def chain_of(self, blocks: list[Block]) -> Blockchain:
        with self.assertLogs("app.core.blockchain", level="ERROR"):
            return Blockchain(self.hash_service, blocks)

    # блок с изменёнными полями и заново посчитанным хешем, как у умного злоумышленника
    def forge(self, block: Block, **changes) -> Block:
        forged = dataclasses.replace(block, **changes)
        forged.hash = forged.compute_hash(self.hash_service)
        return forged

    # исходная цепочка валидна
    def test_intact_chain_is_valid(self):
        self.assertTrue(self.chain.validate_chain())

    # подмена любого поля любой записи без пересчёта хешей
    def test_record_field_tampering(self):
        for position in range(1, BLOCK_COUNT + 1):
            record = self.chain.blocks[position].records[0]
            changes = {
                "record_id": "99999999-9999-4999-8999-999999999999",
                "document_id": "99999999-9999-4999-8999-999999999999",
                "file_hash": "e" * 64,
                "timestamp": record.timestamp + 1,
            }
            for field, value in changes.items():
                with self.subTest(block=position, field=field):
                    blocks = self.fresh_blocks()
                    blocks[position].records[0] = dataclasses.replace(
                        record, **{field: value}
                    )
                    self.assertFalse(self.chain_of(blocks).validate_chain())

    # подмена записи с пересчётом её хеша, хеш блока при этом остаётся прежним
    def test_record_tampering_with_recomputed_record_hash(self):
        blocks = self.fresh_blocks()
        forged = dataclasses.replace(blocks[2].records[0], file_hash="e" * 64)
        forged = dataclasses.replace(
            forged, record_hash=forged.compute_hash(self.hash_service)
        )
        blocks[2].records[0] = forged
        self.assertFalse(self.chain_of(blocks).validate_chain())

    # подмена блока с пересчётом его хеша рвёт ссылку следующего блока
    def test_block_tampering_with_recomputed_hash(self):
        for position in range(1, BLOCK_COUNT):
            with self.subTest(position=position):
                blocks = self.fresh_blocks()
                changed = blocks[position].timestamp + 1
                blocks[position] = self.forge(blocks[position], timestamp=changed)
                self.assertFalse(self.chain_of(blocks).validate_chain())

    # подмена полей блока без пересчёта хеша
    def test_block_field_tampering(self):
        for position in range(BLOCK_COUNT + 1):
            for field, value in (("timestamp", 5), ("index", 99), ("hash", "0" * 64)):
                with self.subTest(position=position, field=field):
                    blocks = self.fresh_blocks()
                    setattr(blocks[position], field, value)
                    self.assertFalse(self.chain_of(blocks).validate_chain())

    # подмена prevHash даже с пересчитанным хешем блока
    def test_prev_hash_tampering(self):
        for position in range(1, BLOCK_COUNT + 1):
            with self.subTest(position=position):
                blocks = self.fresh_blocks()
                blocks[position] = self.forge(blocks[position], prev_hash="d" * 64)
                self.assertFalse(self.chain_of(blocks).validate_chain())

    # перестановка блоков
    def test_blocks_reordering(self):
        blocks = self.fresh_blocks()
        blocks[1], blocks[2] = blocks[2], blocks[1]
        self.assertFalse(self.chain_of(blocks).validate_chain())

    # удаление блока из середины цепочки
    def test_block_removal(self):
        blocks = self.fresh_blocks()
        del blocks[2]
        self.assertFalse(self.chain_of(blocks).validate_chain())

    # подмена genesis
    def test_genesis_tampering(self):
        blocks = self.fresh_blocks()
        blocks[0] = self.forge(blocks[0], prev_hash="c" * 64)
        self.assertFalse(self.chain_of(blocks).validate_chain())

    # ручная правка файла: поле записи, хеш блока и порядок блоков
    def test_manual_edit_of_json_file(self):
        edits = {
            "record field": lambda data: data["blocks"][3]["records"][0].update(
                fileHash="e" * 64
            ),
            "block hash": lambda data: data["blocks"][2].update(hash="e" * 64),
            "block order": lambda data: data["blocks"].reverse(),
        }
        for name, edit in edits.items():
            with self.subTest(edit=name), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "chain.json"
                repository = JsonChainRepository(path)
                repository.save_chain(self.chain.blocks)
                data = json.loads(path.read_text(encoding="utf-8"))
                edit(data)
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertLogs("app.core.blockchain", level="ERROR"):
                    loaded = Blockchain(self.hash_service, repository=repository)
                self.assertFalse(loaded.validate_chain())
                self.assertTrue(loaded.is_blocked)


if __name__ == "__main__":
    unittest.main()
