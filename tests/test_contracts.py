from copy import deepcopy

import pytest

from app.core.block import Block
from app.core.hashing import Blake2bHashService
from app.core.record import Record
from app.network.contracts import APIError, MAX_RECORDS_PER_BLOCK, NETWORK_ID, PROTOCOL_VERSION, ensure_network, ensure_uint, ensure_uuid, parse_block, parse_peer_status, peer_base_url, require_object

DOCUMENT_ID = "a1111111-1111-4111-8111-111111111111"
RECORD_ID = "22222222-2222-4222-8222-222222222222"
GENESIS_HASH = "a" * 64
TIP_HASH = "b" * 64
FILE_HASH = "c" * 64


def assert_api_error(exc_info, status, code):
    error = exc_info.value
    assert error.status == status
    assert error.code == code
    assert isinstance(error.message, str) and error.message
    assert str(error) == error.message


@pytest.fixture
def valid_block():
    hashing = Blake2bHashService()
    record = Record.create(
        DOCUMENT_ID, FILE_HASH, hashing,
        record_id=RECORD_ID, timestamp=1_700_000_000_000,
    )
    return Block.create(
        index=1, prev_hash=GENESIS_HASH, records=[record],
        hash_service=hashing, timestamp=1_700_000_001_000,
    ).to_dict()


@pytest.fixture
def valid_peer_status():
    return {
        "networkId": NETWORK_ID,
        "protocolVersion": PROTOCOL_VERSION,
        "nodeId": "node-A",
        "height": 1,
        "tipHash": TIP_HASH,
        "genesisHash": GENESIS_HASH,
        "chainValid": True,
    }


# Общие контракты


def test_api_error_stores_status_code_and_message():
    error = APIError(418, "TEST_ERROR", "Тестовая ошибка")
    assert error.status == 418
    assert error.code == "TEST_ERROR"
    assert error.message == "Тестовая ошибка"
    assert str(error) == "Тестовая ошибка"


def test_require_object_accepts_exact_field_set():
    obj = {"first": 1, "second": 2}
    assert require_object(obj, {"first", "second"}, "payload") is obj


@pytest.mark.parametrize("bad_obj", [
    None, [], "data", 123, {"first": 1},
    {"first": 1, "second": 2, "third": 3},
], ids=["none", "list", "string", "number", "missing_field", "extra_field"])
def test_require_object_rejects_invalid_objects(bad_obj):
    with pytest.raises(APIError) as exc:
        require_object(bad_obj, {"first", "second"}, "payload")
    assert_api_error(exc, 400, "BAD_REQUEST")
    assert "payload" in exc.value.message


@pytest.mark.parametrize("value", [0, 1, 100, 10**20])
def test_ensure_uint_accepts_nonnegative_integers(value):
    assert ensure_uint(value, "index") is None


@pytest.mark.parametrize("value", [-1, -10, True, False, 1.0, "1", None, [], {}],
                         ids=["minus_one", "minus_ten", "true", "false", "float",
                              "string", "none", "list", "dict"])
def test_ensure_uint_rejects_invalid_values(value):
    with pytest.raises(APIError) as exc:
        ensure_uint(value, "index")
    assert_api_error(exc, 400, "BAD_REQUEST")
    assert "index" in exc.value.message


def test_ensure_uuid_accepts_canonical_lowercase_uuid():
    assert ensure_uuid(DOCUMENT_ID, "documentId") is None


@pytest.mark.parametrize("value", [
    None, 123, "", "not-a-uuid", "11111111111141118111111111111111",
    DOCUMENT_ID.upper(), "{" + DOCUMENT_ID + "}", DOCUMENT_ID + " ",
], ids=["none", "integer", "empty", "invalid", "no_dashes",
        "uppercase", "braces", "trailing_space"])
def test_ensure_uuid_rejects_noncanonical_uuid(value):
    with pytest.raises(APIError) as exc:
        ensure_uuid(value, "documentId")
    assert_api_error(exc, 400, "BAD_REQUEST")
    assert "documentId" in exc.value.message


def test_ensure_network_accepts_matching_network_and_protocol():
    assert ensure_network({"networkId": NETWORK_ID, "protocolVersion": PROTOCOL_VERSION},
                          NETWORK_ID) is None


@pytest.mark.parametrize("change", [
    {"networkId": "another-network"},
    {"protocolVersion": PROTOCOL_VERSION + 1},
    {"networkId": None},
    {"protocolVersion": "1"},
    {"protocolVersion": None},
], ids=["different_network", "different_version", "missing_network_value",
        "version_as_string", "missing_version_value"])
def test_ensure_network_rejects_incompatible_values(change):
    payload = {"networkId": NETWORK_ID, "protocolVersion": PROTOCOL_VERSION}
    payload.update(change)
    with pytest.raises(APIError) as exc:
        ensure_network(payload, NETWORK_ID)
    assert_api_error(exc, 409, "NETWORK_INCOMPATIBLE")


# --- parse_block: структура входящего блока ---


def test_parse_block_returns_actual_block_with_matching_fields(valid_block):
    parsed = parse_block(valid_block)
    assert isinstance(parsed, Block)
    assert parsed.to_dict() == valid_block
    assert parsed.verify(Blake2bHashService())


@pytest.mark.parametrize("bad_data", [
    None, [], "block", {},
    {"index": 1, "timestamp": 1, "prevHash": GENESIS_HASH, "records": []},
    {"index": 1, "timestamp": 1, "prevHash": GENESIS_HASH, "records": [],
     "hash": TIP_HASH, "extra": True},
], ids=["none", "list", "string", "empty", "missing_hash", "extra_field"])
def test_parse_block_rejects_wrong_top_level_structure(bad_data):
    with pytest.raises(APIError) as exc:
        parse_block(bad_data)
    assert_api_error(exc, 400, "BAD_REQUEST")


@pytest.mark.parametrize("field,value", [
    ("index", -1), ("index", True), ("index", "1"),
    ("timestamp", -1), ("timestamp", False), ("timestamp", 2.5),
], ids=["negative_index", "boolean_index", "string_index",
        "negative_timestamp", "boolean_timestamp", "float_timestamp"])
def test_parse_block_rejects_invalid_unsigned_numbers(valid_block, field, value):
    bad = deepcopy(valid_block)
    bad[field] = value
    with pytest.raises(APIError) as exc:
        parse_block(bad)
    assert_api_error(exc, 400, "BAD_REQUEST")


@pytest.mark.parametrize("field,value", [
    ("prevHash", None), ("prevHash", "a" * 63), ("prevHash", "A" * 64),
    ("hash", "g" * 64), ("hash", "b" * 65), ("hash", 123),
], ids=["null_previous", "short_previous", "uppercase_previous",
        "non_hex_hash", "long_hash", "numeric_hash"])
def test_parse_block_rejects_invalid_hash_format(valid_block, field, value):
    bad = deepcopy(valid_block)
    bad[field] = value
    with pytest.raises(APIError) as exc:
        parse_block(bad)
    assert_api_error(exc, 400, "BAD_BLOCK_FORMAT")


@pytest.mark.parametrize("records", [None, {}, "records", [], [None] * 101],
                         ids=["none", "dict", "string", "empty", "too_many"])
def test_parse_block_rejects_invalid_records_container(valid_block, records):
    bad = deepcopy(valid_block)
    bad["records"] = records
    with pytest.raises(APIError) as exc:
        parse_block(bad)
    assert_api_error(exc, 400, "BAD_BLOCK_FORMAT")


def test_parse_block_accepts_maximum_number_of_records(valid_block):
    block = deepcopy(valid_block)
    block["records"] *= MAX_RECORDS_PER_BLOCK
    parsed = parse_block(block)
    assert len(parsed.records) == MAX_RECORDS_PER_BLOCK


@pytest.mark.parametrize("bad_record", [
    None, [], "record", {},
    {"recordId": RECORD_ID, "documentId": DOCUMENT_ID,
     "fileHash": FILE_HASH, "timestamp": 1},
    {"recordId": RECORD_ID, "documentId": DOCUMENT_ID,
     "fileHash": FILE_HASH, "timestamp": 1, "recordHash": TIP_HASH, "extra": True},
], ids=["none", "list", "string", "empty", "missing_record_hash", "extra_field"])
def test_parse_block_rejects_invalid_record_structure(valid_block, bad_record):
    bad = deepcopy(valid_block)
    bad["records"] = [bad_record]
    with pytest.raises(APIError) as exc:
        parse_block(bad)
    assert_api_error(exc, 400, "BAD_REQUEST")


@pytest.mark.parametrize("field,value,expected_code", [
    ("recordId", "no-uuid", "BAD_REQUEST"),
    ("documentId", DOCUMENT_ID.upper(), "BAD_REQUEST"),
    ("timestamp", -1, "BAD_REQUEST"),
    ("timestamp", True, "BAD_REQUEST"),
    ("fileHash", "A" * 64, "BAD_BLOCK_FORMAT"),
    ("recordHash", "a" * 63, "BAD_BLOCK_FORMAT"),
], ids=["bad_record_uuid", "uppercase_document_uuid", "negative_timestamp",
        "boolean_timestamp", "uppercase_file_hash", "short_record_hash"])
def test_parse_block_rejects_invalid_record_fields(valid_block, field, value, expected_code):
    bad = deepcopy(valid_block)
    bad["records"][0][field] = value
    with pytest.raises(APIError) as exc:
        parse_block(bad)
    assert_api_error(exc, 400, expected_code)


def test_parse_block_checks_each_record_not_only_the_first(valid_block):
    bad = deepcopy(valid_block)
    bad["records"].append(deepcopy(bad["records"][0]))
    bad["records"][1]["fileHash"] = "bad"
    with pytest.raises(APIError) as exc:
        parse_block(bad)
    assert_api_error(exc, 400, "BAD_BLOCK_FORMAT")


def test_parse_block_validates_format_not_cryptographic_integrity(valid_block):
    # Проверку подлинности хеша выполняет логика цепочки, а не parse_block.
    bad = deepcopy(valid_block)
    bad["hash"] = "f" * 64
    parsed = parse_block(bad)
    assert parsed.hash == "f" * 64
    assert parsed.verify(Blake2bHashService()) is False


#parse_peer_status: состояние удалённого узла


def test_parse_peer_status_accepts_healthy_peer(valid_peer_status):
    result = parse_peer_status(valid_peer_status, NETWORK_ID, GENESIS_HASH)
    assert result is valid_peer_status


def test_parse_peer_status_accepts_genesis_only_chain(valid_peer_status):
    status = deepcopy(valid_peer_status)
    status.update(height=0, tipHash=GENESIS_HASH)
    assert parse_peer_status(status, NETWORK_ID, GENESIS_HASH) == status


@pytest.mark.parametrize("payload", [None, [], "status", {}, {"networkId": NETWORK_ID}],
                         ids=["none", "list", "string", "empty", "missing_fields"])
def test_parse_peer_status_rejects_invalid_envelope(payload):
    with pytest.raises(APIError) as exc:
        parse_peer_status(payload, NETWORK_ID, GENESIS_HASH)
    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


def test_parse_peer_status_rejects_extra_field(valid_peer_status):
    bad = {**valid_peer_status, "extra": 42}
    with pytest.raises(APIError) as exc:
        parse_peer_status(bad, NETWORK_ID, GENESIS_HASH)
    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


@pytest.mark.parametrize("field,value", [
    ("networkId", "different"),
    ("protocolVersion", PROTOCOL_VERSION + 1),
    ("genesisHash", "f" * 64),
], ids=["different_network", "different_protocol", "different_genesis"])
def test_parse_peer_status_rejects_incompatible_peer(valid_peer_status, field, value):
    bad = {**valid_peer_status, field: value}
    with pytest.raises(APIError) as exc:
        parse_peer_status(bad, NETWORK_ID, GENESIS_HASH)
    assert_api_error(exc, 502, "PEER_INCOMPATIBLE")


@pytest.mark.parametrize("field,value", [
    ("nodeId", None), ("nodeId", ""), ("nodeId", "x" * 81),
    ("height", -1), ("height", True), ("height", 1.5),
    ("tipHash", "G" * 64), ("tipHash", "a" * 63),
    ("chainValid", 1), ("chainValid", "true"),
], ids=["null_node_id", "empty_node_id", "oversized_node_id", "negative_height",
        "boolean_height", "float_height", "non_hex_tip", "short_tip",
        "integer_chain_valid", "string_chain_valid"])
def test_parse_peer_status_rejects_bad_field_types(valid_peer_status, field, value):
    bad = {**valid_peer_status, field: value}
    with pytest.raises(APIError) as exc:
        parse_peer_status(bad, NETWORK_ID, GENESIS_HASH)
    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


def test_parse_peer_status_rejects_invalid_remote_chain(valid_peer_status):
    bad = {**valid_peer_status, "chainValid": False}
    with pytest.raises(APIError) as exc:
        parse_peer_status(bad, NETWORK_ID, GENESIS_HASH)
    assert_api_error(exc, 502, "PEER_CHAIN_INVALID")


def test_parse_peer_status_rejects_genesis_with_wrong_tip(valid_peer_status):
    bad = {**valid_peer_status, "height": 0, "tipHash": TIP_HASH}
    with pytest.raises(APIError) as exc:
        parse_peer_status(bad, NETWORK_ID, GENESIS_HASH)
    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


#peer_base_url: адреса и ограничения доступа


@pytest.mark.parametrize("address,expected", [
    ("http://127.0.0.1:8765", "http://127.0.0.1:8765"),
    ("http://localhost", "http://localhost"),
    ("http://LOCALHOST:80/", "http://localhost:80"),
    ("http://127.10.20.30:8080", "http://127.10.20.30:8080"),
    ("http://[::1]:8765", "http://[::1]:8765"),
], ids=["ipv4", "localhost", "uppercase_localhost_trailing_slash",
        "loopback_127_subnet", "ipv6_loopback"])
def test_peer_base_url_accepts_local_addresses(address, expected):
    assert peer_base_url(address) == expected


@pytest.mark.parametrize("address,expected", [
    ("http://192.168.1.20:5000", "http://192.168.1.20:5000"),
    ("http://example.com:8765", "http://example.com:8765"),
    ("http://[2001:db8::1]:8765", "http://[2001:db8::1]:8765"),
], ids=["remote_ipv4", "remote_dns", "remote_ipv6"])
def test_peer_base_url_allows_remote_only_with_explicit_flag(address, expected):
    with pytest.raises(APIError) as exc:
        peer_base_url(address)
    assert_api_error(exc, 400, "PEER_ADDRESS_FORBIDDEN")
    assert peer_base_url(address, allow_remote=True) == expected


@pytest.mark.parametrize("address", [
    None, 123, "", "x" * 513,
], ids=["none", "integer", "empty", "too_long"])
def test_peer_base_url_rejects_invalid_address_input(address):
    with pytest.raises(APIError) as exc:
        peer_base_url(address)
    assert_api_error(exc, 400, "BAD_PEER_URL")


@pytest.mark.parametrize("address", [
    "127.0.0.1:8765", "https://127.0.0.1:8765", "ftp://localhost",
    "http:///no-host", "http://", "http://user:pass@localhost:8765",
    "http://localhost:8765/api/v1/status", "http://localhost:8765/?token=a",
    "http://localhost:8765/#fragment", "http://localhost:8765/other/",
], ids=["no_scheme", "https", "ftp", "missing_host", "empty_netloc",
        "credentials", "path", "query", "fragment", "other_path"])
def test_peer_base_url_rejects_non_base_or_unsafe_urls(address):
    with pytest.raises(APIError) as exc:
        peer_base_url(address)
    assert_api_error(exc, 400, "BAD_PEER_URL")


@pytest.mark.parametrize("address", [
    "http://localhost:not-a-port", "http://localhost:65536", "http://[::1",
], ids=["non_numeric_port", "port_out_of_range", "broken_ipv6_brackets"])
def test_peer_base_url_rejects_malformed_addresses(address):
    with pytest.raises(APIError) as exc:
        peer_base_url(address)
    assert_api_error(exc, 400, "BAD_PEER_URL")
