import tempfile
import threading
import unittest
from pathlib import Path

from app.network.client import get_json, post_json
from app.network.contracts import APIError, PROTOCOL_VERSION
from app.network.node import Node
from app.network.server import make_server


class BlockAnnouncementTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.node_a = Node("A", root / "a")
        self.node_b = Node("B", root / "b")
        self.url_a = self.start_server(self.node_a)
        self.url_b = self.start_server(self.node_b)
        self.node_b_file = root / "b" / "chain.json"

    def start_server(self, node: Node) -> str:
        server = make_server("127.0.0.1", 0, node)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def announcement(self, index: int, block_hash: str) -> dict:
        return {
            "networkId": self.node_a.network_id,
            "protocolVersion": PROTOCOL_VERSION,
            "sourceUrl": self.url_a,
            "index": index,
            "hash": block_hash,
        }

    def test_receiver_fetches_announced_block_and_persists_it(self):
        created = self.node_a.create_demo_block()
        self.assertEqual(get_json(self.url_b, "/api/v1/status")["height"], 0)

        result = post_json(
            self.url_a, "/api/v1/peers/announce", {"peerUrl": self.url_b}
        )

        self.assertEqual(result["status"], "ACCEPTED")
        self.assertEqual(result["blockHash"], created["blockHash"])
        self.assertEqual(self.node_b.chain.last_block.hash, created["blockHash"])
        self.assertEqual(Node("B-restarted", self.node_b_file.parent).status()["height"], 1)

    def test_repeated_announcement_does_not_rewrite_chain(self):
        self.node_a.create_demo_block()
        self.node_a.announce_latest(self.url_b, self.url_a)
        original_file = self.node_b_file.read_bytes()

        result = self.node_a.announce_latest(self.url_b, self.url_a)

        self.assertEqual(result["status"], "ALREADY_PRESENT")
        self.assertEqual(self.node_b_file.read_bytes(), original_file)

    def test_announcement_hash_mismatch_is_rejected(self):
        self.node_a.create_demo_block()
        original_file = self.node_b_file.read_bytes()

        result = post_json(
            self.url_b,
            "/api/v1/blocks/announce",
            self.announcement(1, "f" * 64),
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["code"], "ANNOUNCEMENT_MISMATCH")
        self.assertEqual(self.node_b_file.read_bytes(), original_file)

    def test_missing_previous_block_is_rejected(self):
        self.node_a.create_demo_block()
        second = self.node_a.create_demo_block()
        original_file = self.node_b_file.read_bytes()

        result = post_json(
            self.url_b,
            "/api/v1/blocks/announce",
            self.announcement(2, second["blockHash"]),
        )

        self.assertEqual(result["code"], "INDEX_MISMATCH")
        self.assertEqual(self.node_b_file.read_bytes(), original_file)

    def test_invalid_received_block_is_rejected_over_http(self):
        self.node_a.create_demo_block()
        envelope = get_json(self.url_a, "/api/v1/blocks/1")
        envelope["block"]["records"][0]["fileHash"] = "b" * 64
        original_file = self.node_b_file.read_bytes()

        result = post_json(self.url_b, "/api/v1/blocks", envelope)

        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["code"], "RECORD_HASH_MISMATCH")
        self.assertEqual(self.node_b_file.read_bytes(), original_file)

    def test_genesis_cannot_be_announced(self):
        with self.assertRaises(APIError) as caught:
            self.node_a.announce_latest(self.url_b, self.url_a)
        self.assertEqual(caught.exception.code, "NO_BLOCK")

    def test_wildcard_binding_requires_reachable_advertised_url(self):
        with self.assertRaises(ValueError):
            make_server("0.0.0.0", 0, self.node_a)


if __name__ == "__main__":
    unittest.main()
