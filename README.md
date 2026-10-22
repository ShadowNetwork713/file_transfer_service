# Secure File Transfer Service

Сервис безопасной передачи файлов с подтверждением их целостности с использованием Blockchain.

## О проекте

Система позволяет загружать, хранить и передавать документы между пользователями. Для каждого файла вычисляется криптографический хеш (BLAKE2), который регистрируется в Blockchain.

Это позволяет в дальнейшем подтвердить, что файл не изменялся после регистрации и существовал в определенный момент времени.

## Основные возможности

* Регистрация и авторизация пользователей
* Загрузка и хранение файлов
* Вычисление BLAKE2 хеша
* Регистрация хеша в Blockchain
* Передача файлов между пользователями
* Проверка целостности документов
* История операций с файлами

## Как это работает

```text
Upload File
      ↓
Generate BLAKE2 Hash
      ↓
Store Hash in Blockchain
      ↓
Transfer / Store Document
      ↓
Verify Integrity
```

При проверке система повторно вычисляет хеш файла и сравнивает его со значением, зарегистрированным в Blockchain.

## Технологии

* Python 3.12, без внешних зависимостей в ядре
* BLAKE2b-256 из стандартной библиотеки (`hashlib`)
* Тесты на `unittest`, линтер `ruff`, менеджер зависимостей `uv`

## Запуск с нуля

Нужен только Python 3.12 или новее.

```bash
git clone <адрес репозитория>
cd file_transfer_service
git switch develop
python -m unittest discover -s tests -t .
```

Линтер (если установлен ruff): `ruff check app tests`.

## Демо

Консольная программа проходит 7 сценариев подряд: создание цепочки с genesis, добавление записей и блоков, сохранение и восстановление, проверка валидной цепочки, подмена записи, подмена хеша блока (разрыв цепочки), проверка внешнего файла.

```bash
python -m app.demo
```

Между сценариями пауза по Enter. Без пауз: `python -m app.demo --no-pause`. Другая папка для данных: `--dir <путь>` (по умолчанию `data/demo`). После каждой подмены `chain.json` возвращается в исходное состояние. Описание сценариев и ожидаемого вывода: `docs/09-demo-scenarios.md`.

Пример вывода сценария с подменой записи:

```text
Сценарий 5. Изменение содержимого записи и обнаружение нарушения
------------------------------------------------------------
  В chain.json изменён fileHash записи в блоке 2
    [лог] Цепочка повреждена. Блок 2: запись ... изменена, хеш записи не совпадает с пересчитанным. Добавление блоков запрещено
  Результат: цепочка НЕ валидна, нарушений: 1
  Проблемный блок: 2
    - Блок 2: запись ... изменена, хеш записи не совпадает с пересчитанным
      ожидалось 3e6d12e3a2190c88..., в блоке d09d937d6be61003...
```

## Ядро блокчейна

Код лежит в `app/core`:

| Файл | Что внутри |
|---|---|
| `hashing.py` | `IHashService`, `Blake2bHashService`: хеш байтов, строки и потока (куски по 64 КБ), hex в нижнем регистре, 64 символа |
| `record.py` | `Record`: запись о документе, хеш считается по каноническому JSON |
| `block.py` | `Block`: блок со списком записей, хеш считается по заголовку |
| `blockchain.py` | `Blockchain`: genesis, `add_block`, `validate_chain`, `validate_report`, `find_break`, `find_records` |
| `validation.py` | `ValidationIssue`, `ValidationReport`, `validate_blocks`: отчёт проверки цепочки с блоком и причиной |
| `storage.py` | `IChainRepository`, `JsonChainRepository`: хранение цепочки в JSON-файле |
| `service.py` | `IBlockchainService`, `BlockchainService`: регистрация документа и проверка внешнего файла |

Демо-программа лежит в `app/demo.py`.

### Как пользоваться

```python
from app.core.blockchain import Blockchain
from app.core.hashing import Blake2bHashService
from app.core.service import BlockchainService
from app.core.storage import JsonChainRepository

hash_service = Blake2bHashService()
chain = Blockchain(hash_service, repository=JsonChainRepository("data/chain.json"))
service = BlockchainService(chain, hash_service)

with open("contract.pdf", "rb") as file:
    file_hash = hash_service.hash_stream(file)

result = service.register_document("11111111-1111-4111-8111-111111111111", file_hash)
print(result.status, result.block_index, result.tx_id)
print(service.validate_chain())
```

### IBlockchainService

| Метод | Что делает |
|---|---|
| `register_document(document_id, file_hash)` | кладёт запись в новый блок и возвращает `RegistrationResult(tx_id, block_index, status, error)` |
| `validate_chain()` | проверяет всю цепочку, `True` если она целая |
| `verify_file(document_id, stream)` | сверяет хеш файла с хешем в последней записи документа и возвращает `FileCheckResult(status, message, current_hash, registered_hash, block_index)` |

* `tx_id` равен `recordHash` записи.
* `status`: `CONFIRMED` после включения в блок, `FAILED` при сбое (повреждённая цепочка, ошибка записи на диск). После `FAILED` регистрацию можно повторить, сам документ не теряется. `PENDING` сейчас не возвращается: блок формируется сразу, значение оставлено для асинхронной схемы.
* Повторная регистрация того же документа с тем же хешем возвращает прежний результат и новый блок не создаёт.
* Неверный UUID или хеш — это ошибка вызова, она приходит как `ValueError`.

### Формат записи

Хеш записи считается по каноническому JSON полей без `recordHash`: ключи по алфавиту, без пробелов. В записи нет имени файла и персональных данных.

```json
{
  "recordId": "22222222-2222-4222-8222-222222222222",
  "documentId": "11111111-1111-4111-8111-111111111111",
  "fileHash": "5e60306500b07808767749f57cc79888d17f6afb993e33505cb29f21381ce91b",
  "timestamp": 1790253000000,
  "recordHash": "a07da2d9a0bde69cfb667e23058c47c7961fddc51bd43563b5abfe869c7e4e49"
}
```

### Формат блока

Хеш блока считается по каноническому JSON заголовка: `index`, `timestamp`, `prevHash` и `recordHashes` (хеши всех записей по порядку).

```json
{
  "index": 1,
  "timestamp": 1790253001000,
  "prevHash": "1c9a8033388f13fa939256e0aa874d636e0ba2ffe64077a2823ddc74d5bcefd5",
  "records": [
    {
      "recordId": "22222222-2222-4222-8222-222222222222",
      "documentId": "11111111-1111-4111-8111-111111111111",
      "fileHash": "5e60306500b07808767749f57cc79888d17f6afb993e33505cb29f21381ce91b",
      "timestamp": 1790253000000,
      "recordHash": "a07da2d9a0bde69cfb667e23058c47c7961fddc51bd43563b5abfe869c7e4e49"
    }
  ],
  "hash": "0a779a525ccb5495a85f985e535ce24ba704f97364e9182331562fa5806222e7"
}
```

Первый блок (genesis) создаётся вручную с фиксированными полями: `index` 0, `timestamp` 0, `prevHash` из 64 нулей, записей нет. Его хеш всегда `1c9a8033388f13fa939256e0aa874d636e0ba2ffe64077a2823ddc74d5bcefd5`.

### Файл цепочки chain.json

```json
{
  "version": 1,
  "blocks": [ { "...": "genesis" }, { "...": "блок 1" } ]
}
```

* Файл создаётся при первом запуске с одним genesis-блоком.
* Запись идёт через временный файл с подменой, поэтому при сбое старый файл не портится.
* При старте цепочка проверяется. Если она повреждена или файл нечитаем, блоки не добавляются, ошибка уходит в лог, а файл остаётся как есть.
* Файл `chain.json` не коммитим.

### Правила цепочки

Цепочка валидна, если:

1. первый блок имеет `index` 0 и `prevHash` из нулей;
2. у каждого блока `index` равен его позиции;
3. пересчитанный хеш блока и хеш каждой записи совпадают с сохранёнными;
4. `prevHash` каждого блока равен `hash` предыдущего.

### Отчёт проверки и точка разрыва

`Blockchain.validate_report()` возвращает `ValidationReport` со списком нарушений. Каждое нарушение (`ValidationIssue`) содержит номер блока, код причины, сообщение, ожидаемое и найденное значение.

| Код | Что не сходится |
|---|---|
| `EMPTY_CHAIN` | в цепочке нет блоков |
| `GENESIS_INVALID` | у первого блока `prevHash` не из нулей |
| `INDEX_MISMATCH` | номер в блоке не равен его позиции |
| `BLOCK_HASH_MISMATCH` | хеш блока не совпадает с пересчитанным |
| `PREV_HASH_MISMATCH` | `prevHash` не совпадает с хешем предыдущего блока (разрыв цепочки) |
| `RECORD_HASH_MISMATCH` | хеш записи не совпадает с пересчитанным |

```python
report = chain.validate_report()
if not report.is_valid:
    print(report.summary())        # Цепочка повреждена. Блок 2: ... (найдено ещё нарушений: 1)
    issue = chain.find_break()     # первое нарушение: issue.block_index, issue.code, issue.message
```

Все нарушения попадают в отчёт, проблемным блоком (точкой разрыва) считается блок первого нарушения. При загрузке `chain.json` строка `report.summary()` пишется в лог, добавление блоков блокируется.

### Проверка внешнего файла

```python
with open("contract.pdf", "rb") as file:
    result = service.verify_file("11111111-1111-4111-8111-111111111111", file)
print(result.status, result.message)
```

| Статус | Когда |
|---|---|
| `VALID` | хеш файла совпадает с `fileHash` последней записи документа |
| `INVALID` | хеши различаются |
| `NOT_FOUND` | документа нет в цепочке |
| `CHAIN_INVALID` | цепочка повреждена, файл подтвердить нельзя (в сообщении блок и причина) |

## Цель проекта

Предоставить механизм независимого подтверждения целостности и времени существования электронных документов без необходимости доверять одной централизованной стороне.

## Статус

Проект находится в разработке.
