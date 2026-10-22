# Документация проекта

Сервис безопасной передачи файлов с подтверждением целостности на основе blockchain.

| Файл | Что внутри | Владелец |
|---|---|---|
| [01-requirements.md](01-requirements.md) | описание, цели, роли пользователей, FR/NFR, User Stories, Use Cases, бизнес-процессы | Аналитик |
| [02-architecture.md](02-architecture.md) | архитектура, модули, БД, потоки; раздел 18: BLAKE2b, свой блокчейн, формат данных, стек | Архитектор |
| [06-diagrams.md](06-diagrams.md) | Use Case, компоненты, классы ядра, последовательности (Mermaid) | Архитектор |
| [03-team-roles.md](03-team-roles.md) | роли в команде, кто что апрувит, RACI | Lead |
| [04-git-workflow.md](04-git-workflow.md) | ветки, коммиты, PR, релизы, связь с YouGile, защита веток | DevOps |
| [sprint-2.md](sprint-2.md) | задачи спринта 2: ядро блокчейна | Lead |
| [sprint-3.md](sprint-3.md) | задачи спринта 3: «честная» цепочка, релиз и демо | Lead |
| [09-demo-scenarios.md](09-demo-scenarios.md) | 7 сценариев демо, критерии приёмки спринта 3, дополнения к глоссарию | Аналитик |
| [07-test-cases.md](07-test-cases.md) | тест-кейсы ядра по UC-1 и UC-2 и результаты прогона | QA |
| [08-acceptance-glossary.md](08-acceptance-glossary.md) | критерии приёмки ядра и глоссарий | Аналитик |
| [05-ci-cd.md](05-ci-cd.md) | CI/CD и деплой не делаем; при необходимости — Gitea + Arcane | DevOps |

Хеш-функция проекта — **BLAKE2b-256**, hex в нижнем регистре.

Эти же материалы дублируются на доску «Документация» в YouGile (`yougile/yg.py`).
