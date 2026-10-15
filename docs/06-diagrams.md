# Диаграммы

Диаграммы написаны на Mermaid: GitHub рисует их прямо в markdown. Для других мест подойдёт https://mermaid.live.

## 1. Use Case диаграмма

```mermaid
flowchart LR
    S([Отправитель])
    R([Получатель])
    A([Администратор])
    G([Гость])
    BC[(Blockchain)]

    subgraph SYS["Сервис безопасной передачи файлов"]
        UC0((Регистрация / вход))
        UC1((UC-1 Загрузить и зарегистрировать документ))
        UC2((UC-2 Проверить целостность))
        UC3((UC-3 Передать документ))
        UC4((UC-4 Получить и скачать документ))
        UC5((Просмотреть историю))
        UC6((Публичная проверка по файлу/хешу))
        UC7((Управление пользователями))
        UC8((Мониторинг цепочки и журнала))
    end

    S --- UC0 & UC1 & UC2 & UC3 & UC5
    R --- UC0 & UC4 & UC2
    G --- UC6
    A --- UC7 & UC8
    UC1 -. include .-> BC
    UC2 -. include .-> BC
    UC6 -. include .-> BC
```

## 2. Диаграмма компонентов

```mermaid
flowchart TB
    U[Браузер пользователя] -->|HTTPS| FE[Frontend SPA<br/>React + TS]
    FE -->|REST /api| API

    subgraph API["Backend API — модульный монолит (Python, FastAPI)"]
        AUTH[Auth]
        DOC[Documents]
        ACC[Access]
        INT[Integrity<br/>BLAKE2b-256]
        BCM[Blockchain Module<br/>IBlockchainService]
        AUD[Audit]
        DOC --> INT
        DOC --> BCM
        DOC --> ACC
        DOC --> AUD
        ACC --> AUD
    end

    subgraph CORE["Ядро блокчейна"]
        CHAIN[Blockchain]
        BLK[Block]
        REC[Record]
        CHAIN --> BLK --> REC
    end

    BCM --> CORE
    API --> PG[(PostgreSQL<br/>метаданные + цепочка)]
    DOC --> FS[(File Storage<br/>файлы)]
```

## 3. Диаграмма классов ядра

```mermaid
classDiagram
    class IHashService {
        <<interface>>
        +HashStream(Stream) string
        +HashBytes(byte[]) string
    }
    class Blake2bHashService {
        -int DigestSize = 32
        +HashStream(Stream) string
        +HashBytes(byte[]) string
    }
    class Record {
        +UUID RecordId
        +UUID DocumentId
        +string FileHash
        +long Timestamp
        +string RecordHash
        +ComputeHash(IHashService) string
        +ToCanonicalJson() string
        +Verify(IHashService) bool
    }
    class Block {
        +int Index
        +long Timestamp
        +string PrevHash
        +list~Record~ Records
        +string Hash
        +ComputeHash(IHashService) string
        +Verify(IHashService) bool
    }
    class Blockchain {
        -list~Block~ chain
        +CreateGenesis() Block
        +AddBlock(list~Record~) Block
        +ValidateChain() bool
    }
    class IBlockchainService {
        <<interface>>
        +RegisterDocument(UUID, string) RegistrationResult
        +ValidateChain() bool
    }
    class IChainRepository {
        <<interface>>
        +LoadChain() list~Block~
        +SaveChain(list~Block~)
    }
    class JsonChainRepository {
        -Path path
        +LoadChain() list~Block~
        +SaveChain(list~Block~)
    }

    IHashService <|.. Blake2bHashService
    IChainRepository <|.. JsonChainRepository
    Blockchain "1" o-- "*" Block
    Block "1" o-- "*" Record
    Blockchain ..> IHashService
    IBlockchainService ..> Blockchain
    Blockchain ..> IChainRepository
```

## 4. Диаграмма последовательности: загрузка и регистрация (UC-1)

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant FE as Frontend
    participant API as Documents
    participant FS as File Storage
    participant H as Integrity (BLAKE2b)
    participant DB as PostgreSQL
    participant BC as Blockchain Module

    U->>FE: выбрать файл
    FE->>API: POST /documents (multipart)
    API->>API: проверка JWT, размера, формата
    API->>FS: сохранить файл (storage_key)
    API->>H: HashStream(file)
    H-->>API: fileHash (hex, 64)
    API->>DB: INSERT document (status=HASH_CALCULATED)
    API->>BC: RegisterDocument(documentId, fileHash)
    BC->>BC: AddBlock([record]), SaveChain в chain.json
    BC-->>API: recordHash, blockIndex, status=CONFIRMED
    API->>DB: UPDATE status=CONFIRMED, transaction_hash, block_number
    API-->>FE: 201 {id, hash, status: CONFIRMED, blockIndex}
    Note over BC: при сбое FAILED, регистрацию можно повторить
```

## 5. Диаграмма последовательности: проверка целостности (UC-2)

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant FE as Frontend
    participant API as Integrity
    participant H as BLAKE2b
    participant DB as PostgreSQL
    participant BC as Blockchain Module

    U->>FE: загрузить файл для проверки
    FE->>API: POST /verify (file)
    API->>H: HashStream(file)
    H-->>API: currentHash
    API->>DB: получить зарегистрированный hash_blake2b документа
    DB-->>API: registeredHash
    API->>BC: ValidateChain()
    BC-->>API: true / false
    alt хеши равны и цепочка валидна
        API-->>FE: VALID
    else хеши различаются или цепочка повреждена
        API-->>FE: INVALID
    end
    Note over API,BC: поиск записи по хешу файла (GetProof) появится в следующем спринте
```
