import io
import unittest

from app.core.hashing import CHUNK_SIZE, Blake2bHashService, is_valid_hash

EMPTY_HASH = "0e5751c026e543b2e8ab2eb06099daa1d1e5df47778f7787faab45cdf12fe3a8"


class ZeroStream:
    # поток нулей заданного размера, который ничего не хранит в памяти
    def __init__(self, size: int):
        self.left = size
        self.max_read = 0

    # отдаёт не больше size байт и запоминает самый большой запрос
    def read(self, size: int = -1) -> bytes:
        self.max_read = max(self.max_read, size)
        count = min(size, self.left)
        self.left -= count
        return bytes(count)


class Blake2bHashServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = Blake2bHashService()

    # контрольный вектор для пустой строки
    def test_empty_input_matches_control_vector(self):
        self.assertEqual(self.service.hash_bytes(b""), EMPTY_HASH)
        self.assertEqual(self.service.hash_text(""), EMPTY_HASH)
        self.assertEqual(self.service.hash_stream(io.BytesIO(b"")), EMPTY_HASH)

    # результат это hex в нижнем регистре длиной 64
    def test_output_format(self):
        result = self.service.hash_text("Документ")
        self.assertEqual(len(result), 64)
        self.assertTrue(is_valid_hash(result))
        self.assertEqual(result, result.lower())

    # поток и байты дают одинаковый хеш, в том числе на нескольких кусках
    def test_stream_equals_bytes(self):
        data = bytes(range(256)) * (CHUNK_SIZE // 100)
        self.assertGreater(len(data), CHUNK_SIZE)
        self.assertEqual(
            self.service.hash_stream(io.BytesIO(data)),
            self.service.hash_bytes(data),
        )

    # разное содержимое даёт разный хеш
    def test_different_input_gives_different_hash(self):
        self.assertNotEqual(
            self.service.hash_bytes(b"a"), self.service.hash_bytes(b"b")
        )

    # файл на 100 мб хешируется кусками и не читается в память целиком
    def test_large_stream_is_read_in_chunks(self):
        stream = ZeroStream(100 * 1024 * 1024)
        result = self.service.hash_stream(stream)
        self.assertEqual(stream.left, 0)
        self.assertLessEqual(stream.max_read, CHUNK_SIZE)
        self.assertTrue(is_valid_hash(result))

    # проверка формата хеша отклоняет лишнее
    def test_is_valid_hash_rejects_bad_values(self):
        for value in ("", "abc", EMPTY_HASH.upper(), EMPTY_HASH + "0", None, 5):
            with self.subTest(value=value):
                self.assertFalse(is_valid_hash(value))
        self.assertTrue(is_valid_hash(EMPTY_HASH))


if __name__ == "__main__":
    unittest.main()
