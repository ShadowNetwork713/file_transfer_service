import uuid
from unittest.mock import Mock

import pytest

from app.core.service import RegistrationResult, RegistrationStatus
from app.network import node as node_module
from app.network.contracts import APIError, NETWORK_ID, PROTOCOL_VERSION

PEER_URL = "http://127.0.0.1:8765"
DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
FILE_HASH = "a" * 64


@pytest.fixture
def node(tmp_path):
    return node_module.Node("A", tmp_path / "node_a")


@pytest.fixture
def other_node(tmp_path):
    return node_module.Node("B", tmp_path / "node_b")


def assert_api_error(exc_info, status, code):
    assert exc_info.value.status == status
    assert exc_info.value.code == code


def make_peer_ahead(other_node):
    other_node.create_document(DOCUMENT_ID, FILE_HASH)
    return other_node.status(), other_node.get_block(1)


#Создание узла и работа с локальной цепочкой


@pytest.mark.parametrize("bad_id", [None, 123, "", "x" * 81])
def test_node_rejects_invalid_id(tmp_path, bad_id):
    with pytest.raises(ValueError, match="node_id"):
        node_module.Node(bad_id, tmp_path / "invalid")


def test_node_initial_status(node, tmp_path):
    status = node.status()
    assert status == {
        "networkId": NETWORK_ID,
        "protocolVersion": PROTOCOL_VERSION,
        "nodeId": "A",
        "height": 0,
        "tipHash": node.genesis_hash,
        "genesisHash": node.genesis_hash,
        "chainValid": True,
    }
    assert (tmp_path / "node_a" / "chain.json").is_file()


def test_node_restores_chain_after_restart(tmp_path):
    path = tmp_path / "persistent"
    first = node_module.Node("A", path)
    first.create_document(DOCUMENT_ID, FILE_HASH)
    restarted = node_module.Node("A", path)
    assert restarted.status()["height"] == 1
    assert restarted.status()["tipHash"] == first.status()["tipHash"]
    assert restarted.status()["chainValid"] is True


def test_node_status_detects_corrupted_chain(node):
    node.create_document(DOCUMENT_ID, FILE_HASH)
    node.chain.blocks[1].timestamp += 1
    assert node.status()["chainValid"] is False


def test_get_block_returns_envelope(node):
    node.create_document(DOCUMENT_ID, FILE_HASH)
    result = node.get_block(1)
    assert result == {
        "networkId": NETWORK_ID,
        "protocolVersion": PROTOCOL_VERSION,
        "block": node.chain.blocks[1].to_dict(),
    }


@pytest.mark.parametrize("index", [-1, 1, 99])
def test_get_block_rejects_missing_index(node, index):
    with pytest.raises(APIError) as exc:
        node.get_block(index)
    assert_api_error(exc, 404, "BLOCK_NOT_FOUND")


def test_get_block_rejects_corrupted_chain(node):
    node.create_document(DOCUMENT_ID, FILE_HASH)
    node.chain.blocks[1].timestamp += 1
    with pytest.raises(APIError) as exc:
        node.get_block(1)
    assert_api_error(exc, 409, "CHAIN_INVALID")


def test_create_document_registers_block(node):
    result = node.create_document(DOCUMENT_ID, FILE_HASH)
    assert result["status"] == "CONFIRMED"
    assert result["blockIndex"] == 1
    assert result["blockHash"] == node.status()["tipHash"]
    assert result["txId"] == node.chain.blocks[1].records[0].record_hash
    assert node.chain.blocks[1].records[0].document_id == DOCUMENT_ID


def test_create_document_repeated_request_is_idempotent(node):
    first = node.create_document(DOCUMENT_ID, FILE_HASH)
    second = node.create_document(DOCUMENT_ID, FILE_HASH)
    assert second == first
    assert node.status()["height"] == 1


@pytest.mark.parametrize("document_id", ["invalid-uuid", "", None])
def test_create_document_rejects_invalid_uuid(node, document_id):
    with pytest.raises(APIError) as exc:
        node.create_document(document_id, FILE_HASH)
    assert_api_error(exc, 400, "BAD_REQUEST")


@pytest.mark.parametrize("file_hash", ["ABC" * 21 + "A", "a" * 63, "z" * 64, 42])
def test_create_document_rejects_invalid_hash(node, file_hash):
    with pytest.raises(APIError) as exc:
        node.create_document(DOCUMENT_ID, file_hash)
    assert_api_error(exc, 400, "BAD_REQUEST")


def test_create_document_reports_registration_failure(node, monkeypatch):
    monkeypatch.setattr(
        node.service,
        "register_document",
        lambda *_: RegistrationResult(None, None, RegistrationStatus.FAILED, "disk error"),
    )
    with pytest.raises(APIError) as exc:
        node.create_document(DOCUMENT_ID, FILE_HASH)
    assert_api_error(exc, 409, "REGISTRATION_FAILED")


def test_create_demo_block_uses_generated_uuid(node, monkeypatch):
    fixed_uuid = uuid.UUID(DOCUMENT_ID)
    monkeypatch.setattr(node_module.uuid, "uuid4", lambda: fixed_uuid)
    result = node.create_demo_block()
    expected = node.hash_service.hash_text(f"demo:A:{DOCUMENT_ID}")
    assert result["status"] == "CONFIRMED"
    assert node.chain.blocks[1].records[0].file_hash == expected


#Приём внешнего блока


@pytest.mark.parametrize("envelope", [None, {}, {"block": {}}, {"networkId": NETWORK_ID, "protocolVersion": PROTOCOL_VERSION, "block": {}, "extra": 1}])
def test_accept_block_requires_exact_envelope(node, envelope):
    with pytest.raises(APIError) as exc:
        node.accept_block(envelope)
    assert_api_error(exc, 400, "BAD_REQUEST")


def test_accept_block_rejects_other_network(node, other_node):
    _, envelope = make_peer_ahead(other_node)
    envelope["networkId"] = "another-network"
    with pytest.raises(APIError) as exc:
        node.accept_block(envelope)
    assert_api_error(exc, 409, "NETWORK_INCOMPATIBLE")


def test_accept_block_rejects_bad_block_format(node):
    envelope = {"networkId": NETWORK_ID, "protocolVersion": PROTOCOL_VERSION, "block": {"index": 1}}
    with pytest.raises(APIError) as exc:
        node.accept_block(envelope)
    assert_api_error(exc, 400, "BAD_REQUEST")


def test_accept_block_and_duplicate(node, other_node):
    _, envelope = make_peer_ahead(other_node)
    first = node.accept_block(envelope)
    second = node.accept_block(envelope)
    assert first["status"] == "ACCEPTED"
    assert second["status"] == "ALREADY_PRESENT"
    assert first["blockIndex"] == second["blockIndex"] == 1
    assert node.status()["tipHash"] == other_node.status()["tipHash"]


def test_accept_block_persists_after_restart(node, other_node, tmp_path):
    _, envelope = make_peer_ahead(other_node)
    assert node.accept_block(envelope)["status"] == "ACCEPTED"
    restarted = node_module.Node("A", tmp_path / "node_a")
    assert restarted.status()["height"] == 1
    assert restarted.status()["tipHash"] == other_node.status()["tipHash"]


def test_accept_block_rejects_tampered_hash(node, other_node):
    _, envelope = make_peer_ahead(other_node)
    envelope["block"]["hash"] = "f" * 64
    result = node.accept_block(envelope)
    assert result["status"] == "REJECTED"
    assert node.status()["height"] == 0


def test_accept_block_returns_rejection(node, other_node, monkeypatch):
    _, envelope = make_peer_ahead(other_node)

    class FakeRejectedBlockError(Exception):
        code = "BLOCK_CONFLICT"

    def reject(_block):
        raise FakeRejectedBlockError("Блок не продолжает цепочку")

    monkeypatch.setattr(node_module, "RejectedBlockError", FakeRejectedBlockError)
    monkeypatch.setattr(node.chain, "append_external_block", reject, raising=False)
    result = node.accept_block(envelope)
    assert result["status"] == "REJECTED"
    assert result["code"] == "BLOCK_CONFLICT"
    assert result["blockIndex"] == 1


#Статус удалённого пира


def test_peer_status_validates_response(node, other_node, monkeypatch):
    remote_status = other_node.status()
    get = Mock(return_value=remote_status)
    monkeypatch.setattr(node_module, "get_json", get)
    assert node.peer_status(PEER_URL) == remote_status
    get.assert_called_once_with(PEER_URL, "/api/v1/status", timeout=2.0)


@pytest.mark.parametrize("changes,expected", [
    ({"networkId": "wrong"}, "PEER_INCOMPATIBLE"),
    ({"genesisHash": "f" * 64}, "PEER_INCOMPATIBLE"),
    ({"chainValid": False}, "PEER_CHAIN_INVALID"),
    ({"height": "one"}, "PEER_BAD_RESPONSE"),
])
def test_peer_status_rejects_invalid_remote(node, other_node, monkeypatch, changes, expected):
    raw = {**other_node.status(), **changes}
    monkeypatch.setattr(node_module, "get_json", lambda *_args, **_kwargs: raw)
    with pytest.raises(APIError) as exc:
        node.peer_status(PEER_URL)
    assert_api_error(exc, 502, expected)


def test_peer_status_forbids_nonlocal_address(node, monkeypatch):
    get = Mock()
    monkeypatch.setattr(node_module, "get_json", get)
    with pytest.raises(APIError) as exc:
        node.peer_status("http://example.org:8765")
    assert_api_error(exc, 400, "PEER_ADDRESS_FORBIDDEN")
    get.assert_not_called()


#Загрузка одного блока (pull)


def test_pull_one_accepts_next_block(node, other_node, monkeypatch):
    remote_status, envelope = make_peer_ahead(other_node)
    get = Mock(side_effect=[remote_status, envelope])
    monkeypatch.setattr(node_module, "get_json", get)
    result = node.pull_one(PEER_URL)
    assert result["status"] == "ACCEPTED"
    assert node.status()["tipHash"] == other_node.status()["tipHash"]
    assert [call.args[1] for call in get.call_args_list] == ["/api/v1/status", "/api/v1/blocks/1"]


def test_pull_one_only_adds_one_of_two_blocks(node, other_node, monkeypatch):
    other_node.create_document(DOCUMENT_ID, FILE_HASH)
    other_node.create_document(str(uuid.uuid4()), "b" * 64)
    remote_status = other_node.status()
    envelope = other_node.get_block(1)
    monkeypatch.setattr(node_module, "get_json", Mock(side_effect=[remote_status, envelope]))
    assert node.pull_one(PEER_URL)["status"] == "ACCEPTED"
    assert node.status()["height"] == 1
    assert other_node.status()["height"] == 2


@pytest.mark.parametrize("scenario,expected_status,expected_code", [
    ("behind", "REJECTED", "PEER_BEHIND"),
    ("same_conflict", "REJECTED", "BLOCK_CONFLICT"),
    ("same_ok", "ALREADY_SYNCED", "OK"),
    ("local_invalid", "REJECTED", "CHAIN_INVALID"),
])
def test_pull_one_handles_heights_and_local_chain(node, other_node, monkeypatch, scenario, expected_status, expected_code):
    if scenario in ("behind", "same_conflict", "local_invalid"):
        node.create_document(DOCUMENT_ID, FILE_HASH)
    remote = other_node.status()
    if scenario == "same_conflict":
        other_node.create_document(str(uuid.uuid4()), FILE_HASH)
        remote = other_node.status()
    if scenario == "local_invalid":
        monkeypatch.setattr(node.chain, "validate_chain", lambda: False)
    monkeypatch.setattr(node, "peer_status", lambda *_: remote)
    get = Mock()
    monkeypatch.setattr(node_module, "get_json", get)
    result = node.pull_one(PEER_URL)
    assert (result["status"], result["code"]) == (expected_status, expected_code)
    get.assert_not_called()


@pytest.mark.parametrize("bad_response,expected_code", [
    (None, "PEER_BAD_RESPONSE"),
    ({"networkId": "wrong", "protocolVersion": PROTOCOL_VERSION, "block": {}}, "PEER_INCOMPATIBLE"),
    ({"networkId": NETWORK_ID, "protocolVersion": PROTOCOL_VERSION, "block": {}, "extra": True}, "PEER_BAD_RESPONSE"),
    ({"networkId": NETWORK_ID, "protocolVersion": PROTOCOL_VERSION, "block": {}}, "PEER_BAD_RESPONSE"),
])
def test_pull_one_rejects_bad_block_response(node, other_node, monkeypatch, bad_response, expected_code):
    remote, _ = make_peer_ahead(other_node)
    monkeypatch.setattr(node, "peer_status", lambda *_: remote)
    monkeypatch.setattr(node_module, "get_json", lambda *_args, **_kwargs: bad_response)
    with pytest.raises(APIError) as exc:
        node.pull_one(PEER_URL)
    assert_api_error(exc, 502, expected_code)


def test_pull_one_rejects_wrong_block_index(node, other_node, monkeypatch):
    remote, envelope = make_peer_ahead(other_node)
    envelope["block"]["index"] = 7
    monkeypatch.setattr(node, "peer_status", lambda *_: remote)
    monkeypatch.setattr(node_module, "get_json", lambda *_args, **_kwargs: envelope)
    with pytest.raises(APIError) as exc:
        node.pull_one(PEER_URL)
    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")


#Отправка одного блока (push)


@pytest.mark.parametrize("scenario,expected_status,expected_code", [
    ("peer_ahead", "REJECTED", "PEER_AHEAD"),
    ("same_conflict", "REJECTED", "BLOCK_CONFLICT"),
    ("same_ok", "ALREADY_SYNCED", "OK"),
    ("local_invalid", "REJECTED", "CHAIN_INVALID"),
])
def test_push_one_handles_heights_and_local_chain(node, other_node, monkeypatch, scenario, expected_status, expected_code):
    if scenario == "peer_ahead":
        other_node.create_document(DOCUMENT_ID, FILE_HASH)
    elif scenario == "same_conflict":
        node.create_document(DOCUMENT_ID, FILE_HASH)
        other_node.create_document(str(uuid.uuid4()), FILE_HASH)
    elif scenario == "local_invalid":
        monkeypatch.setattr(node.chain, "validate_chain", lambda: False)
    monkeypatch.setattr(node, "peer_status", lambda *_: other_node.status())
    post = Mock()
    monkeypatch.setattr(node_module, "post_json", post)
    result = node.push_one(PEER_URL)
    assert (result["status"], result["code"]) == (expected_status, expected_code)
    post.assert_not_called()


def test_push_one_sends_next_block(node, other_node, monkeypatch):
    node.create_document(DOCUMENT_ID, FILE_HASH)
    monkeypatch.setattr(node, "peer_status", lambda *_: other_node.status())
    envelope = node.get_block(1)
    response = {
        "status": "ACCEPTED", "code": "OK", "message": "Блок принят",
        "blockIndex": 1, "blockHash": envelope["block"]["hash"],
    }
    post = Mock(return_value=response)
    monkeypatch.setattr(node_module, "post_json", post)
    assert node.push_one(PEER_URL) == response
    post.assert_called_once_with(PEER_URL, "/api/v1/blocks", envelope, timeout=2.0)


def test_push_one_sends_only_next_of_two_blocks(node, other_node, monkeypatch):
    node.create_document(DOCUMENT_ID, FILE_HASH)
    node.create_document(str(uuid.uuid4()), "b" * 64)
    other_node.accept_block(node.get_block(1))
    monkeypatch.setattr(node, "peer_status", lambda *_: other_node.status())
    post = Mock(return_value={
        "status": "ACCEPTED", "code": "OK", "message": "Принят",
        "blockIndex": 2, "blockHash": node.get_block(2)["block"]["hash"],
    })
    monkeypatch.setattr(node_module, "post_json", post)
    assert node.push_one(PEER_URL)["status"] == "ACCEPTED"
    assert post.call_args.args[2]["block"]["index"] == 2


@pytest.mark.parametrize("status,code", [
    ("ALREADY_PRESENT", "OK"),
    ("REJECTED", "BLOCK_CONFLICT"),
])
def test_push_one_handles_valid_peer_replies(node, other_node, monkeypatch, status, code):
    node.create_document(DOCUMENT_ID, FILE_HASH)
    monkeypatch.setattr(node, "peer_status", lambda *_: other_node.status())
    response = {
        "status": status, "code": code, "message": "Ответ пира",
        "blockIndex": 1, "blockHash": node.get_block(1)["block"]["hash"],
    }
    monkeypatch.setattr(node_module, "post_json", lambda *_args, **_kwargs: response)
    assert node.push_one(PEER_URL) == response


@pytest.mark.parametrize("change", [
    None,
    {"status": "UNKNOWN"},
    {"status": "ACCEPTED", "code": "ERROR"},
    {"code": 123},
    {"message": None},
    {"blockIndex": True},
    {"blockIndex": 2},
    {"blockHash": "f" * 64},
    {"extra": 1},
])
def test_push_one_rejects_invalid_peer_confirmation(node, other_node, monkeypatch, change):
    node.create_document(DOCUMENT_ID, FILE_HASH)
    monkeypatch.setattr(node, "peer_status", lambda *_: other_node.status())
    good = {
        "status": "ACCEPTED", "code": "OK", "message": "Блок принят",
        "blockIndex": 1, "blockHash": node.get_block(1)["block"]["hash"],
    }
    reply = None if change is None else {**good, **change}
    monkeypatch.setattr(node_module, "post_json", lambda *_args, **_kwargs: reply)
    with pytest.raises(APIError) as exc:
        node.push_one(PEER_URL)
    assert_api_error(exc, 502, "PEER_BAD_RESPONSE")
