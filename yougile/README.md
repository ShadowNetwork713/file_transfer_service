# Работа с YouGile через API

Инструмент для работы с доской проекта **«Сервис безопасной передачи файлов»** через YouGile REST API v2:
перенос задач между колонками, описания, создание задач, комментарии, отметки о выполнении.

## Правила

- Ключ хранится только в `.env` в корне репозитория (`YOUGILE_API_KEY`). В код, коммиты, README и чат его не пишем. `.env` лежит в `.gitignore`.
- Работаем только внутри проекта из `YOUGILE_PROJECT_TITLE`. `yg.py` проверяет, что задача из нашего проекта, и отказывается трогать чужие (например, **Cursur**).
- Перед массовыми изменениями делаем прогон с `--dry`.
- Документацию, которую нужно разнести по задачам, кладём в `docs/`, а описания задач берём оттуда через `--file`.

## Команды

```bash
python yougile/yg.py tree                          # доски → колонки → задачи (с id)
python yougile/yg.py task <taskId>                 # карточка: колонка, исполнители, описание
python yougile/yg.py move <taskId> "В работе"      # перетащить (имя колонки или id; --board если имя неуникально)
python yougile/yg.py desc <taskId> --file docs/auth.md          # заменить описание
python yougile/yg.py desc <taskId> "ещё абзац" --append         # дописать в конец
python yougile/yg.py create "Название" --column "Бэклог" --file docs/x.md --assign <userId> --deadline 2026-10-15
python yougile/yg.py update <taskId> --title "..." --assign <id1> <id2> --sticker <stickerId>=<stateId>
python yougile/yg.py done <taskId>  [--undo]
python yougile/yg.py comment <taskId> "текст"
python yougile/yg.py users [--all]                 # участники проекта (или вся компания)
python yougile/yg.py stickers                      # стикеры и их состояния
python yougile/yg.py dump                          # снимок проекта в yougile/snapshot.json
python yougile/yg.py --dry move <taskId> "Готово"  # показать запрос без изменений
```

Описание пишется в markdown-lite: `- пункт`, `# заголовок`, `**жирный**`, `` `код` ``, ссылки. В YouGile оно уходит как HTML. Если текст уже в HTML, добавь флаг `--html`.

Скрипт использует только стандартную библиотеку, Python 3.8+.

## Шпаргалка по API

База: `https://ru.yougile.com/api-v2`, заголовок `Authorization: Bearer <key>`. Лимит около 50 запросов в минуту, на 429 `yg.py` сам ждёт и повторяет.

| Что | Запрос |
|---|---|
| Проекты | `GET /projects` |
| Доски проекта | `GET /boards?projectId=` |
| Колонки доски | `GET /columns?boardId=` |
| Задачи колонки | `GET /task-list?columnId=` |
| Задача | `GET /tasks/{id}` |
| Создать задачу | `POST /tasks` `{title, columnId, description, assigned[], deadline:{deadline:ms}, stickers{}}` |
| Изменить / перенести | `PUT /tasks/{id}` `{columnId, title, description, completed, archived, assigned, stickers}` |
| Комментарий в чат задачи | `POST /chats/{taskId}/messages` `{text, textHtml, label}` |
| Пользователи | `GET /users` |
| Стикеры | `GET /string-stickers`, `GET /sprint-stickers` |
| Ключи | `POST /auth/keys/get`, `POST /auth/keys`, `DELETE /auth/keys/{key}` |

Списки отдаются как `{paging:{next}, content:[]}` и берутся через `limit`/`offset`. Удалённые объекты приходят с `deleted: true`, `yg.py` их отфильтровывает.
