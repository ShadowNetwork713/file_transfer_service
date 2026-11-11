import ipaddress
import uuid
from urllib.parse import urlsplit

from app.core.block import Block
from app.core.hashing import is_valid_hash

NETWORK_ID = "demo-v1"
PROTOCOL_VERSION = 1
MAX_BODY_BYTES = 256 * 1024
MAX_RECORDS_PER_BLOCK = 100


class APIError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def require_object(value, fields, name):
    if not isinstance(value, dict) or set(value) != fields:
        raise APIError(400, "BAD_REQUEST", f"{name}: ожидаются поля {', '.join(sorted(fields))}")
    return value


def ensure_uint(value, name):
    if type(value) is not int or value < 0:
        raise APIError(400, "BAD_REQUEST", f"{name} должен быть неотрицательным целым числом")


def ensure_uuid(value, name):
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        valid = False
    if not valid:
        raise APIError(400, "BAD_REQUEST", f"{name} должен быть UUID в каноническом формате")


def ensure_network(raw, network_id):
    if raw.get("networkId") != network_id or raw.get("protocolVersion") != PROTOCOL_VERSION:
        raise APIError(409, "NETWORK_INCOMPATIBLE", "Идентификатор сети или версия протокола не совпадают")


def parse_block(raw):
    block = require_object(raw, {"index", "timestamp", "prevHash", "records", "hash"}, "block")
    ensure_uint(block["index"], "index")
    ensure_uint(block["timestamp"], "timestamp")
    if not is_valid_hash(block["prevHash"]) or not is_valid_hash(block["hash"]):
        raise APIError(400, "BAD_BLOCK_FORMAT", "prevHash и hash должны быть hex длиной 64")
    records = block["records"]
    if not isinstance(records, list) or not (1 <= len(records) <= MAX_RECORDS_PER_BLOCK):
        raise APIError(400, "BAD_BLOCK_FORMAT", "Ожидается от 1 до 100 записей")
    for raw_record in records:
        record = require_object(raw_record, {"recordId", "documentId", "fileHash", "timestamp", "recordHash"}, "record")
        ensure_uuid(record["recordId"], "recordId")
        ensure_uuid(record["documentId"], "documentId")
        ensure_uint(record["timestamp"], "record.timestamp")
        if not is_valid_hash(record["fileHash"]) or not is_valid_hash(record["recordHash"]):
            raise APIError(400, "BAD_BLOCK_FORMAT", "fileHash и recordHash должны быть hex длиной 64")
    return Block.from_dict(block)


def parse_peer_status(raw, expected_network_id, expected_genesis):
    if not isinstance(raw, dict) or set(raw) != {
        "networkId", "protocolVersion", "nodeId", "height", "tipHash", "genesisHash", "chainValid"
    }:
        raise APIError(502, "PEER_BAD_RESPONSE", "Неправильный формат состояния пира")
    if raw["networkId"] != expected_network_id or raw["protocolVersion"] != PROTOCOL_VERSION or raw["genesisHash"] != expected_genesis:
        raise APIError(502, "PEER_INCOMPATIBLE", "Несовместимая сеть, genesis или версия протокола")
    if (not isinstance(raw["nodeId"], str) or not 1 <= len(raw["nodeId"]) <= 80
        or type(raw["height"]) is not int or raw["height"] < 0
        or not is_valid_hash(raw["tipHash"]) or type(raw["chainValid"]) is not bool):
        raise APIError(502, "PEER_BAD_RESPONSE", "Некорректные типы полей состояния пира")
    if not raw["chainValid"]:
        raise APIError(502, "PEER_CHAIN_INVALID", "Цепочка удалённого пира повреждена")
    if raw["height"] == 0 and raw["tipHash"] != expected_genesis:
        raise APIError(502, "PEER_BAD_RESPONSE", "У пира несовместимая вершина genesis")
    return raw


def peer_base_url(address, allow_remote = False):
    if not isinstance(address, str) or len(address) > 512:
        raise APIError(400, "BAD_PEER_URL", "Укажите HTTP-адрес пира")
    try:
        parts = urlsplit(address)
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise APIError(400, "BAD_PEER_URL", "Некорректный порт или адрес пира") from exc
    if (parts.scheme != "http" or not hostname or not parts.netloc
        or parts.username is not None or parts.password is not None
        or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise APIError(400, "BAD_PEER_URL", "Нужен адрес вида http://127.0.0.1:8765 без пути и параметров")
    if not allow_remote:
        try:
            local = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            local = hostname.lower() == "localhost"
        if not local:
            raise APIError(400, "PEER_ADDRESS_FORBIDDEN", "В демо разрешены только localhost и 127.0.0.1")
    host = f"[{hostname}]" if ":" in hostname else hostname
    return f"http://{host}:{port}" if port is not None else f"http://{host}"
