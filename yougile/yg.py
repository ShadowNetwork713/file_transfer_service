#!/usr/bin/env python3
"""YouGile CLI для проекта «Сервис безопасной передачи файлов».

Ключ читается из .env (корень репозитория) или из переменной окружения YOUGILE_API_KEY.
Все операции записи разрешены ТОЛЬКО внутри проекта YOUGILE_PROJECT_TITLE —
задачи других проектов (например, Cursur) скрипт трогать отказывается.

Примеры:
  python yougile/yg.py tree                         # доски → колонки → задачи
  python yougile/yg.py task <taskId>                # карточка задачи
  python yougile/yg.py move <taskId> "В работе"     # перетащить в колонку (по имени или id)
  python yougile/yg.py desc <taskId> --file d.md    # заменить описание
  python yougile/yg.py desc <taskId> --append "текст"
  python yougile/yg.py create "Сделать X" --column "Бэклог" --desc "..." --assign <userId>
  python yougile/yg.py done <taskId> [--undo]
  python yougile/yg.py comment <taskId> "текст"
  python yougile/yg.py users | stickers | dump
Флаг --dry перед командой: показать запрос, ничего не менять.
"""
import argparse, html, json, os, re, sys, time, urllib.error, urllib.request
from datetime import datetime

BASE = "https://ru.yougile.com/api-v2"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def load_env():
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
KEY = os.environ.get("YOUGILE_API_KEY", "")
PROJECT_TITLE = os.environ.get("YOUGILE_PROJECT_TITLE", "Сервис безопасной передачи файлов")
DRY = False


def die(msg):
    print("Ошибка:", msg, file=sys.stderr)
    sys.exit(1)


def call(method, path, body=None):
    if not KEY:
        die("нет YOUGILE_API_KEY (.env или окружение)")
    if DRY and method != "GET":
        print(f"[dry] {method} {path}\n{json.dumps(body, ensure_ascii=False, indent=2)}")
        return {}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={
        "Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:  # лимит ~50 запросов/мин
                time.sleep(2 * (attempt + 1)); continue
            die(f"{method} {path} → HTTP {e.code}: {e.read().decode()[:300]}")
        except urllib.error.URLError as e:
            die(f"{method} {path} → сеть: {e.reason}")


def all_items(path):
    out, off = [], 0
    sep = "&" if "?" in path else "?"
    while True:
        j = call("GET", f"{path}{sep}limit=1000&offset={off}")
        out += [x for x in j.get("content", []) if not x.get("deleted")]
        if not j.get("paging", {}).get("next"):
            return out
        off += 1000


# ---------- проект и его структура ----------
_cache = {}


def project():
    if "p" not in _cache:
        ps = [p for p in all_items("/projects") if p["title"].strip().lower() == PROJECT_TITLE.strip().lower()]
        if not ps:
            titles = ", ".join(p["title"] for p in all_items("/projects"))
            die(f"проект «{PROJECT_TITLE}» не найден этим ключом. Видны: {titles}")
        _cache["p"] = ps[0]
    return _cache["p"]


def boards():
    if "b" not in _cache:
        _cache["b"] = all_items(f"/boards?projectId={project()['id']}")
    return _cache["b"]


def columns(board_id=None):
    cols = []
    for b in boards():
        if board_id and b["id"] != board_id:
            continue
        for c in all_items(f"/columns?boardId={b['id']}"):
            c["_board"] = b
            cols.append(c)
    return cols


def resolve_column(ref, board=None):
    b_id = None
    if board:
        bs = [b for b in boards() if b["id"] == board or b["title"].lower() == board.lower()]
        if not bs:
            die(f"доска «{board}» не найдена в проекте")
        b_id = bs[0]["id"]
    cols = columns(b_id)
    m = [c for c in cols if c["id"] == ref] or [c for c in cols if c["title"].strip().lower() == ref.strip().lower()]
    if not m:
        die(f"колонка «{ref}» не найдена. Есть: " + ", ".join(f"{c['_board']['title']}/{c['title']}" for c in cols))
    if len(m) > 1:
        die("колонка с таким именем есть на нескольких досках, укажи --board: " + ", ".join(c["_board"]["title"] for c in m))
    return m[0]


def guard_task(task_id):
    """Задача обязана принадлежать нашему проекту."""
    t = call("GET", f"/tasks/{task_id}")
    col_ids = {c["id"]: c for c in columns()}
    if t.get("columnId") not in col_ids:
        die(f"задача {task_id} не из проекта «{PROJECT_TITLE}» — не трогаю")
    t["_col"] = col_ids[t["columnId"]]
    return t


# ---------- описание: markdown-lite → HTML ----------
def to_html(text, raw_html=False):
    if raw_html:
        return text
    out, in_list = [], False
    for line in text.splitlines():
        s = line.rstrip()
        li = re.match(r"^\s*[-*]\s+(.*)", s)
        if li:
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{inline(li.group(1))}</li>"); continue
        if in_list:
            out.append("</ul>"); in_list = False
        h = re.match(r"^(#{1,3})\s+(.*)", s)
        if h:
            out.append(f"<p><strong>{inline(h.group(2))}</strong></p>")
        elif s:
            out.append(f"<p>{inline(s)}</p>")
    if in_list:
        out.append("</ul>")
    return "".join(out)


def inline(s):
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return re.sub(r"(https?://\S+)", r'<a href="\1">\1</a>', s)


def to_text(h):
    h = re.sub(r"<(br|/p|/li|/ul)[^>]*>", "\n", h or "")
    h = re.sub(r"<li[^>]*>", "- ", h)
    return html.unescape(re.sub(r"<[^>]+>", "", h)).strip()


def read_text(a):
    if getattr(a, "file", None):
        return open(a.file, encoding="utf-8").read()
    return a.text or ""


# ---------- команды ----------
def cmd_tree(a):
    p = project()
    print(f"Проект: {p['title']}  ({p['id']})")
    for b in boards():
        print(f"\n■ {b['title']}  ({b['id']})")
        for c in all_items(f"/columns?boardId={b['id']}"):
            ts = all_items(f"/task-list?columnId={c['id']}")
            if not a.archived:
                ts = [t for t in ts if not t.get("archived")]
            print(f"  ▸ {c['title']}  [{len(ts)}]  ({c['id']})")
            for t in ts:
                mark = "✔" if t.get("completed") else "·"
                print(f"     {mark} {t['title']}  ({t['id']})")


def cmd_task(a):
    t = guard_task(a.id)
    print(f"{t['title']}\nid: {t['id']}\nколонка: {t['_col']['_board']['title']} / {t['_col']['title']}")
    print(f"выполнена: {bool(t.get('completed'))}, в архиве: {bool(t.get('archived'))}")
    if t.get("assigned"):
        print("исполнители:", ", ".join(t["assigned"]))
    if t.get("deadline", {}).get("deadline"):
        print("дедлайн:", datetime.fromtimestamp(t["deadline"]["deadline"] / 1000).date())
    if t.get("stickers"):
        print("стикеры:", json.dumps(t["stickers"], ensure_ascii=False))
    print("\nОписание:\n" + (to_text(t.get("description")) or "—"))
    if a.json:
        print(json.dumps(t, ensure_ascii=False, indent=2, default=str))


def cmd_move(a):
    t = guard_task(a.id)
    c = resolve_column(a.column, a.board)
    call("PUT", f"/tasks/{t['id']}", {"columnId": c["id"]})
    print(f"«{t['title']}»: {t['_col']['title']} → {c['title']}")


def cmd_desc(a):
    t = guard_task(a.id)
    new = to_html(read_text(a), a.html)
    if a.append:
        new = (t.get("description") or "") + new
    call("PUT", f"/tasks/{t['id']}", {"description": new})
    print(f"описание «{t['title']}» обновлено")


def cmd_create(a):
    c = resolve_column(a.column, a.board)
    body = {"title": a.title, "columnId": c["id"]}
    if a.text or a.file:
        body["description"] = to_html(read_text(a), a.html)
    if a.assign:
        body["assigned"] = a.assign
    if a.deadline:
        body["deadline"] = {"deadline": int(datetime.strptime(a.deadline, "%Y-%m-%d").timestamp() * 1000)}
    r = call("POST", "/tasks", body)
    print(f"создана «{a.title}» в {c['title']}: {r.get('id', '(dry)')}")


def cmd_update(a):
    t = guard_task(a.id)
    body = {}
    if a.title: body["title"] = a.title
    if a.assign is not None: body["assigned"] = a.assign
    if a.deadline:
        body["deadline"] = {"deadline": int(datetime.strptime(a.deadline, "%Y-%m-%d").timestamp() * 1000)}
    if a.archive: body["archived"] = True
    if a.sticker:
        st = dict(t.get("stickers") or {})
        for s in a.sticker:
            k, _, v = s.partition("=")
            st[k] = v
        body["stickers"] = st
    if not body:
        die("нечего менять")
    call("PUT", f"/tasks/{t['id']}", body)
    print(f"«{t['title']}» обновлена: {', '.join(body)}")


def cmd_done(a):
    t = guard_task(a.id)
    call("PUT", f"/tasks/{t['id']}", {"completed": not a.undo})
    print(f"«{t['title']}»: {'снята отметка' if a.undo else 'выполнена'}")


def cmd_comment(a):
    t = guard_task(a.id)
    text = read_text(a)
    call("POST", f"/chats/{t['id']}/messages", {"text": text, "textHtml": to_html(text), "label": ""})
    print(f"комментарий к «{t['title']}» отправлен")


def cmd_users(a):
    members = project().get("users", {})
    for u in all_items("/users"):
        if a.all or u["id"] in members:
            print(f"{u['id']}  {u.get('realName','')}  <{u.get('email','')}>  {members.get(u['id'],'')}")


def cmd_stickers(a):
    bids = {b["id"] for b in boards()}
    for kind in ("string-stickers", "sprint-stickers"):
        for s in all_items(f"/{kind}"):
            print(f"[{kind}] {s['name']}  ({s['id']})")
            for st in s.get("states", []):
                if not st.get("deleted"):
                    print(f"    {st.get('name')}  ({st['id']})")
    print("\nСтикеры, подключённые к доскам проекта:")
    for b in boards():
        print(f"  {b['title']}: {json.dumps(b.get('stickers', {}), ensure_ascii=False)}")


def cmd_dump(a):
    p = project()
    snap = {"project": p, "boards": []}
    for b in boards():
        cols = []
        for c in all_items(f"/columns?boardId={b['id']}"):
            c["tasks"] = all_items(f"/task-list?columnId={c['id']}")
            cols.append(c)
        snap["boards"].append({**b, "columns": cols})
    out = os.path.join(ROOT, "yougile", "snapshot.json")
    json.dump(snap, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("снимок:", out)


def main():
    global DRY
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="не менять, только показать запросы")
    sp = ap.add_subparsers(dest="cmd", required=True)

    def text_args(p, positional=False):
        if positional:
            p.add_argument("text", nargs="?")
        else:
            p.add_argument("--desc", dest="text")
        p.add_argument("--file", help="взять текст из файла (markdown-lite)")
        p.add_argument("--html", action="store_true", help="текст уже HTML")

    p = sp.add_parser("tree"); p.add_argument("--archived", action="store_true"); p.set_defaults(f=cmd_tree)
    p = sp.add_parser("task"); p.add_argument("id"); p.add_argument("--json", action="store_true"); p.set_defaults(f=cmd_task)
    p = sp.add_parser("move"); p.add_argument("id"); p.add_argument("column"); p.add_argument("--board"); p.set_defaults(f=cmd_move)
    p = sp.add_parser("desc"); p.add_argument("id"); text_args(p, True); p.add_argument("--append", action="store_true"); p.set_defaults(f=cmd_desc)
    p = sp.add_parser("create"); p.add_argument("title"); p.add_argument("--column", required=True); p.add_argument("--board")
    text_args(p); p.add_argument("--assign", nargs="*"); p.add_argument("--deadline", help="YYYY-MM-DD"); p.set_defaults(f=cmd_create)
    p = sp.add_parser("update"); p.add_argument("id"); p.add_argument("--title"); p.add_argument("--assign", nargs="*")
    p.add_argument("--deadline"); p.add_argument("--archive", action="store_true")
    p.add_argument("--sticker", nargs="*", help="stickerId=stateId"); p.set_defaults(f=cmd_update)
    p = sp.add_parser("done"); p.add_argument("id"); p.add_argument("--undo", action="store_true"); p.set_defaults(f=cmd_done)
    p = sp.add_parser("comment"); p.add_argument("id"); text_args(p, True); p.set_defaults(f=cmd_comment)
    p = sp.add_parser("users"); p.add_argument("--all", action="store_true"); p.set_defaults(f=cmd_users)
    sp.add_parser("stickers").set_defaults(f=cmd_stickers)
    sp.add_parser("dump").set_defaults(f=cmd_dump)

    a = ap.parse_args()
    DRY = a.dry
    a.f(a)


if __name__ == "__main__":
    main()
