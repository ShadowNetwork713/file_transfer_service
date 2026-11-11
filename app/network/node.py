import threading
import uuid
from pathlib import Path

from app.core.blockchain import Blockchain, RejectedBlockError
from app.core.hashing import Blake2bHashService, is_valid_hash
from app.core.service import BlockchainService
from app.core.storage import JsonChainRepository
from app.network.client import get_json
from app.network.contracts import (
    APIError, NETWORK_ID, PROTOCOL_VERSION, ensure_network,
    ensure_uuid, parse_block, parse_peer_status, peer_base_url,
)


class Node:
    def __init__(self, node_id, data_dir, *, network_id=NETWORK_ID,
                 allow_remote_peers=False, timeout=2.0):
        if not isinstance(node_id, str) or not 1 <= len(node_id) <= 80:
            raise ValueError("node_id: ожидается строка длиной 1..80")
        self.node_id = node_id
        self.network_id = network_id
        self.allow_remote_peers = allow_remote_peers
        self.timeout = timeout
        self.lock = threading.RLock()
        self.hash_service = Blake2bHashService()
        self.chain = Blockchain(self.hash_service, repository=JsonChainRepository(Path(data_dir) / "chain.json"))
        self.service = BlockchainService(self.chain, self.hash_service)
        self.genesis_hash = self.chain.create_genesis().hash

    def status(self):
        with self.lock:
            return {
                "networkId": self.network_id,
                "protocolVersion": PROTOCOL_VERSION,
                "nodeId": self.node_id,
                "height": len(self.chain) - 1,
                "tipHash": self.chain.last_block.hash,
                "genesisHash": self.genesis_hash,
                "chainValid": self.chain.validate_chain(),
            }

    def get_block(self, index):
        with self.lock:
            if index < 0 or index >= len(self.chain):
                raise APIError(404, "BLOCK_NOT_FOUND", f"Блок {index} отсутствует")
            if not self.chain.validate_chain():
                raise APIError(409, "CHAIN_INVALID", "Локальная цепочка повреждена")
            return {"networkId": self.network_id, "protocolVersion": PROTOCOL_VERSION,
                    "block": self.chain.blocks[index].to_dict()}

    def create_document(self, document_id, file_hash):
        ensure_uuid(document_id, "documentId")
        if not is_valid_hash(file_hash):
            raise APIError(400, "BAD_REQUEST", "fileHash должен быть 64-символьным lowercase hex")
        with self.lock:
            result = self.service.register_document(document_id, file_hash)
            if result.status == "FAILED":
                raise APIError(409, "REGISTRATION_FAILED", result.error or "Ошибка регистрации")
            return {"status": str(result.status), "txId": result.tx_id,
                    "blockIndex": result.block_index,
                    "blockHash": self.chain.blocks[result.block_index].hash}

    def create_demo_block(self):
        document_id = str(uuid.uuid4())
        file_hash = self.hash_service.hash_text(f"demo:{self.node_id}:{document_id}")
        return self.create_document(document_id, file_hash)

    def accept_block(self, envelope):
        if not isinstance(envelope, dict) or set(envelope) != {"networkId", "protocolVersion", "block"}:
            raise APIError(400, "BAD_REQUEST", "Ожидаются networkId, protocolVersion и block")
        ensure_network(envelope, self.network_id)
        block = parse_block(envelope["block"])
        with self.lock:
            try:
                added = self.chain.append_external_block(block)
            except RejectedBlockError as exc:
                return {"status": "REJECTED", "code": exc.code, "message": str(exc),
                        "blockIndex": block.index, "blockHash": block.hash}
            return {"status": "ACCEPTED" if added else "ALREADY_PRESENT",
                    "code": "OK", "message": "Блок принят и сохранён" if added else "Идентичный блок уже имеется",
                    "blockIndex": block.index, "blockHash": block.hash}

    def peer_status(self, peer_url):
        url = peer_base_url(peer_url, self.allow_remote_peers)
        raw = get_json(url, "/api/v1/status", timeout=self.timeout)
        return parse_peer_status(raw, self.network_id, self.genesis_hash)

    def pull_one(self, peer_url):
        url = peer_base_url(peer_url, self.allow_remote_peers)
        peer = self.peer_status(url)
        with self.lock:
            local = self.status()
            if not local["chainValid"]:
                return {"status": "REJECTED", "code": "CHAIN_INVALID", "message": "Локальная цепочка повреждена"}
            if peer["height"] < local["height"]:
                return {"status": "REJECTED", "code": "PEER_BEHIND", "message": "Высота пира меньше локальной"}
            if peer["height"] == local["height"]:
                if peer["tipHash"] != local["tipHash"]:
                    return {"status": "REJECTED", "code": "BLOCK_CONFLICT", "message": "Разные вершины на одной высоте"}
                return {"status": "ALREADY_SYNCED", "code": "OK", "message": "Вершины цепочек уже совпадают"}
            next_index = local["height"] + 1
        envelope = get_json(url, f"/api/v1/blocks/{next_index}", timeout=self.timeout)
        if not isinstance(envelope, dict):
            raise APIError(502, "PEER_BAD_RESPONSE", "Некорректный ответ с блоком")
        if envelope.get("networkId") != self.network_id or envelope.get("protocolVersion") != PROTOCOL_VERSION:
            raise APIError(502, "PEER_INCOMPATIBLE", "Несовместимый ответ с блоком")
        try:
            if set(envelope) != {"networkId", "protocolVersion", "block"}:
                raise APIError(400, "BAD_REQUEST", "Некорректная структура ответа")
            block = parse_block(envelope["block"])
        except APIError as exc:
            raise APIError(502, "PEER_BAD_RESPONSE", str(exc)) from exc
        if block.index != next_index:
            raise APIError(502, "PEER_BAD_RESPONSE", "Пир вернул блок с неверным индексом")
        return self.accept_block(envelope)
