import argparse
import json
import logging
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from app.core.block import Block
from app.core.blockchain import Blockchain
from app.core.hashing import Blake2bHashService
from app.core.service import BlockchainService
from app.core.storage import JsonChainRepository
from app.core.validation import ValidationReport

DEMO_FILES = {
    "contract.pdf": "Договор поставки N17. Сумма 120 000 руб. Срок до 01.12.2026.",
    "report.docx": "Отчёт о выполнении работ за октябрь 2026 года.",
    "notes.txt": "Протокол встречи команды: итоги третьего спринта.",
}
SHORT = 16


class Demo:
    def __init__(
        self, out: TextIO, data_dir: Path, reader: Callable[[str], str] | None
    ):
        self.out = out
        self.reader = reader
        self.files_dir = data_dir / "files"
        self.chain_path = data_dir / "chain.json"
        self.hash_service = Blake2bHashService()
        self.doc_ids = {
            name: str(uuid.uuid5(uuid.NAMESPACE_URL, name)) for name in DEMO_FILES
        }
        self.names = {doc_id: name for name, doc_id in self.doc_ids.items()}

    # печатает строку в выбранный поток
    def say(self, text: str = "") -> None:
        print(text, file=self.out)

    # заголовок сценария
    def scenario(self, number: int, title: str) -> None:
        self.say()
        self.say(f"Сценарий {number}. {title}")
        self.say("-" * 60)

    # пауза до нажатия Enter, чтобы успеть показать экран
    def wait(self) -> None:
        if self.reader is not None:
            self.reader("\nНажмите Enter, чтобы продолжить...")

    # короткая запись хеша для экрана
    def short(self, value: object) -> str:
        text = str(value)
        return text[:SHORT] + "..." if len(text) > SHORT else text

    # открывает цепочку из файла, при отсутствии файла создаётся genesis
    def open_chain(self) -> Blockchain:
        repository = JsonChainRepository(self.chain_path)
        return Blockchain(self.hash_service, repository=repository)

    # печатает блок: номер, связь с предыдущим, записи и хеш
    def show_block(self, block: Block) -> None:
        self.say(f"  Блок {block.index}")
        self.say(f"    prevHash : {self.short(block.prev_hash)}")
        for record in block.records:
            name = self.names.get(record.document_id, record.document_id)
            self.say(
                f"    запись   : {name}, recordHash {self.short(record.record_hash)}"
            )
        self.say(f"    hash     : {self.short(block.hash)}")

    # печатает результат проверки цепочки с проблемным блоком и причиной
    def show_report(self, report: ValidationReport) -> None:
        if report.is_valid:
            self.say("  Результат: цепочка валидна, нарушений нет")
            return
        self.say(f"  Результат: цепочка НЕ валидна, нарушений: {len(report.issues)}")
        self.say(f"  Проблемный блок: {report.issues[0].block_index}")
        for issue in report.issues:
            self.say(f"    - {issue.message}")
            if issue.expected is not None:
                self.say(
                    f"      ожидалось {self.short(issue.expected)}, "
                    f"в блоке {self.short(issue.actual)}"
                )

    # правит chain.json так, как это сделал бы злоумышленник
    def tamper(self, edit: Callable[[dict], None]) -> None:
        data = json.loads(self.chain_path.read_text(encoding="utf-8"))
        edit(data)
        self.chain_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # создаёт файлы документов для демо
    def prepare_files(self) -> None:
        self.files_dir.mkdir(parents=True, exist_ok=True)
        for name, text in DEMO_FILES.items():
            (self.files_dir / name).write_text(text, encoding="utf-8")
        self.chain_path.unlink(missing_ok=True)

    # хеш файла документа потоком
    def file_hash(self, name: str) -> str:
        with open(self.files_dir / name, "rb") as stream:
            return self.hash_service.hash_stream(stream)

    # сценарий 1: новый блокчейн с genesis
    def scenario_1(self) -> Blockchain:
        self.scenario(1, "Создание нового блокчейна с genesis-блоком")
        chain = self.open_chain()
        self.say(f"  Файл цепочки создан: {self.chain_path}")
        self.show_block(chain.blocks[0])
        self.say("  Genesis создан вручную: номер 0, prevHash из нулей, записей нет")
        self.wait()
        return chain

    # сценарий 2: записи и блоки, хеши и связи
    def scenario_2(self, chain: Blockchain) -> None:
        self.scenario(2, "Добавление записей и блоков, хеши и связи между блоками")
        service = BlockchainService(chain, self.hash_service)
        for name in DEMO_FILES:
            result = service.register_document(self.doc_ids[name], self.file_hash(name))
            self.say(
                f"  Регистрация {name}: {result.status}, блок {result.block_index}"
            )
            self.show_block(chain.last_block)
            previous = chain.blocks[chain.last_block.index - 1]
            self.say(
                f"    prevHash равен hash блока {previous.index}: "
                f"{chain.last_block.prev_hash == previous.hash}"
            )
        self.wait()

    # сценарий 3: сохранение, перезапуск и восстановление
    def scenario_3(self, chain: Blockchain) -> None:
        self.scenario(3, "Сохранение, перезапуск и восстановление цепочки")
        size = self.chain_path.stat().st_size
        self.say(f"  Цепочка сохранена в {self.chain_path} ({size} байт)")
        self.say("  Перезапуск программы: цепочка читается из файла заново")
        restored = self.open_chain()
        same = restored.blocks == chain.blocks
        self.say(
            f"  Восстановлено блоков: {len(restored)}, содержимое совпадает: {same}"
        )
        for block in restored.blocks:
            self.say(f"    блок {block.index}: hash {self.short(block.hash)}")
        self.wait()

    # сценарий 4: проверка корректной цепочки
    def scenario_4(self) -> None:
        self.scenario(4, "Проверка валидности корректной цепочки")
        chain = self.open_chain()
        self.say("  Проверяем: хеш каждого блока, ссылку prevHash и хеш каждой записи")
        self.show_report(chain.validate_report())
        self.wait()

    # сценарий 5: подмена содержимого записи
    def scenario_5(self) -> None:
        self.scenario(5, "Изменение содержимого записи и обнаружение нарушения")
        backup = self.chain_path.read_text(encoding="utf-8")
        target = "0" * 63 + "1"
        self.tamper(
            lambda data: data["blocks"][2]["records"][0].update(fileHash=target)
        )
        self.say("  В chain.json изменён fileHash записи в блоке 2")
        chain = self.open_chain()
        self.show_report(chain.validate_report())
        self.chain_path.write_text(backup, encoding="utf-8")
        self.say("  Файл цепочки возвращён в исходное состояние")
        self.wait()

    # сценарий 6: подмена хеша предыдущего блока
    def scenario_6(self) -> None:
        self.scenario(6, "Изменение хеша предыдущего блока и обнаружение разрыва")
        backup = self.chain_path.read_text(encoding="utf-8")
        self.tamper(lambda data: data["blocks"][2].update(hash="f" * 64))
        self.say("  В chain.json изменён hash блока 2, а блок 3 ссылается на старый")
        chain = self.open_chain()
        self.show_report(chain.validate_report())
        self.say("  Блок 3 больше не ведёт к блоку 2, цепочка разорвана")
        self.chain_path.write_text(backup, encoding="utf-8")
        self.say("  Файл цепочки возвращён в исходное состояние")
        self.wait()

    # сценарий 7: проверка внешнего файла
    def scenario_7(self) -> None:
        self.scenario(7, "Проверка внешнего файла")
        service = BlockchainService(self.open_chain(), self.hash_service)
        name = "contract.pdf"
        path = self.files_dir / name
        original = path.read_text(encoding="utf-8")
        self.check_file(service, name, "файл не менялся")
        path.write_text(original.replace("120 000", "950 000"), encoding="utf-8")
        self.check_file(service, name, "в файле изменена сумма")
        path.write_text(original, encoding="utf-8")
        unknown = str(uuid.uuid4())
        with open(path, "rb") as stream:
            result = service.verify_file(unknown, stream)
        self.say(f"  Неизвестный документ: {result.status}. {result.message}")

    # сверяет файл документа с цепочкой и печатает результат
    def check_file(self, service: BlockchainService, name: str, note: str) -> None:
        with open(self.files_dir / name, "rb") as stream:
            result = service.verify_file(self.doc_ids[name], stream)
        self.say(f"  {name} ({note}): {result.status}")
        self.say(f"    {result.message}")
        self.say(
            f"    в записи {self.short(result.registered_hash)}, "
            f"у файла {self.short(result.current_hash)}"
        )

    # все сценарии подряд
    def run_all(self) -> None:
        self.say(
            "Демо ядра блокчейна: BLAKE2b-256, цепочка блоков, проверка целостности"
        )
        self.prepare_files()
        chain = self.scenario_1()
        self.scenario_2(chain)
        self.scenario_3(chain)
        self.scenario_4()
        self.scenario_5()
        self.scenario_6()
        self.scenario_7()
        self.say()
        self.say("Демо завершено")


# запускает демо, ошибки цепочки из лога выводятся в тот же поток
def run(out: TextIO, data_dir: Path, pause: bool = True) -> None:
    logger = logging.getLogger("app.core")
    handler = logging.StreamHandler(out)
    handler.setLevel(logging.ERROR)
    handler.setFormatter(logging.Formatter("    [лог] %(message)s"))
    logger.addHandler(handler)
    try:
        Demo(out, data_dir, input if pause else None).run_all()
    finally:
        logger.removeHandler(handler)


# точка входа: python -m app.demo
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Демо ядра блокчейна")
    parser.add_argument("--dir", default="data/demo", help="папка для данных демо")
    parser.add_argument("--no-pause", action="store_true", help="без пауз между шагами")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    run(sys.stdout, Path(args.dir), pause=not args.no_pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
