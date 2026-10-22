import hashlib
import re
from typing import BinaryIO, Protocol

CHUNK_SIZE = 64 * 1024
DIGEST_SIZE = 32

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


# проверяет, что строка это hex в нижнем регистре длиной 64
def is_valid_hash(value: object) -> bool:
    return isinstance(value, str) and _HASH_PATTERN.fullmatch(value) is not None


class IHashService(Protocol):
    # хеш байтов
    def hash_bytes(self, data: bytes) -> str: ...

    # хеш строки в utf-8
    def hash_text(self, text: str) -> str: ...

    # хеш потока без загрузки всего содержимого в память
    def hash_stream(self, stream: BinaryIO) -> str: ...


class Blake2bHashService:
    # хеш байтов целиком
    def hash_bytes(self, data: bytes) -> str:
        return hashlib.blake2b(data, digest_size=DIGEST_SIZE).hexdigest()

    # хеш строки в utf-8
    def hash_text(self, text: str) -> str:
        return self.hash_bytes(text.encode("utf-8"))

    # хеш потока кусками по 64 кб
    def hash_stream(self, stream: BinaryIO) -> str:
        digest = hashlib.blake2b(digest_size=DIGEST_SIZE)
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
        return digest.hexdigest()
