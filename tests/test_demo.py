import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from app import demo
from app.core.blockchain import Blockchain
from app.core.hashing import Blake2bHashService
from app.core.storage import JsonChainRepository


class DemoTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name) / "demo"

    # запускает демо без пауз и возвращает весь вывод
    def run_demo(self) -> str:
        out = io.StringIO()
        demo.run(out, self.data_dir, pause=False)
        return out.getvalue()

    # в выводе есть все 7 сценариев
    def test_all_scenarios_are_shown(self):
        text = self.run_demo()
        for number in range(1, 8):
            self.assertIn(f"Сценарий {number}.", text)
        self.assertIn("Демо завершено", text)

    # хеши и связи блоков показаны, genesis создан
    def test_hashes_and_links_are_shown(self):
        text = self.run_demo()
        self.assertIn("Блок 0", text)
        self.assertIn("prevHash равен hash блока 2: True", text)
        self.assertIn("Восстановлено блоков: 4, содержимое совпадает: True", text)

    # подмена записи указывает проблемный блок и причину
    def test_record_tampering_is_reported(self):
        text = self.run_demo()
        self.assertIn("Проблемный блок: 2", text)
        self.assertIn("запись", text)
        self.assertIn("хеш записи не совпадает с пересчитанным", text)

    # подмена хеша блока показывает разрыв
    def test_chain_break_is_reported(self):
        text = self.run_demo()
        self.assertIn("Блок 3: prevHash не совпадает с хешем блока 2", text)
        self.assertIn("цепочка разорвана", text)

    # проверка внешнего файла даёт VALID, INVALID и NOT_FOUND
    def test_file_check_results(self):
        text = self.run_demo()
        self.assertIn("(файл не менялся): VALID", text)
        self.assertIn("(в файле изменена сумма): INVALID", text)
        self.assertIn("Неизвестный документ: NOT_FOUND", text)

    # ошибки цепочки попадают в вывод из лога
    def test_log_lines_are_in_output(self):
        self.assertIn("[лог] Цепочка повреждена", self.run_demo())

    # после демо файл цепочки возвращён в исходное состояние и валиден
    def test_chain_file_is_restored(self):
        self.run_demo()
        chain = Blockchain(
            Blake2bHashService(),
            repository=JsonChainRepository(self.data_dir / "chain.json"),
        )
        self.assertEqual(len(chain), 4)
        self.assertTrue(chain.validate_chain())

    # повторный запуск начинает с чистой цепочки
    def test_rerun_starts_fresh(self):
        first = self.run_demo()
        second = self.run_demo()
        self.assertIn("Регистрация contract.pdf: CONFIRMED, блок 1", second)
        self.assertEqual(first.count("Сценарий"), second.count("Сценарий"))

    # точка входа с аргументами работает и возвращает 0
    def test_main_entry_point(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = demo.main(["--no-pause", "--dir", str(self.data_dir)])
        self.assertEqual(code, 0)
        self.assertIn("Демо завершено", out.getvalue())

    # демо не оставляет обработчик логов после себя
    def test_log_handler_is_removed(self):
        import logging

        before = list(logging.getLogger("app.core").handlers)
        self.run_demo()
        self.assertEqual(logging.getLogger("app.core").handlers, before)


if __name__ == "__main__":
    unittest.main()
