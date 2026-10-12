import os
import re
import ast
import time
import random
import operator
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta

from vkbottle.bot import Bot, Message
from vkbottle.dispatch.rules.base import ChatActionRule

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("VK_TOKEN", "vk1.a.2lK6gUJyCKD7Um7C1NSgzThDCvvG0WYr0ElFxxz-Tqw2Btf3O-__wzuAKWpJNRFmsA--au9LUpV4ec1_4qQRRTJFOTo0u2JHEu0SDV2BehMDWuQpQG_sugbHMJ8xoiDTLMsTqKaXLBlqyX2gy1fq6g5oSH0N8L0c62nnjQw4rTqE7uoKPRKy4fl8jsf5YmU3UmkfU5NVhpCX5CMmfVNWVw")
OWNERS = {int(x) for x in os.getenv("OWNER_IDS", "1020224655").split(",") if x.strip()}
PROJECT = os.getenv("PROJECT_NAME", "Flin RP")
MAX_WARNS = 3
MAX_VIGS = 3
DB_PATH = os.getenv("DB_PATH", "chatmanager.db")

ROLES = {0: "Игрок", 1: "Хелпер", 2: "Администратор", 3: "Главный администратор", 4: "Владелец"}
MSK = timezone(timedelta(hours=3))
START = time.time()
ZW = "\u200b"

DEFAULT_WELCOME = "Добро пожаловать в беседу {project}, {name}. Правила: /rules. Все команды: /help."
DEFAULT_ABOUT = (
    f"{PROJECT} — SAMP RP-проект. Первое открытие: 2017 год. "
    "Проект возвращается после года простоя: обновляются ПК-лаунчер, мобильный лаунчер и мод.\n"
    "Адрес сервера: /ip\nЛаунчеры и кэш: /launcher\nДата релиза: /release\n"
    "Набор в команду: /apply"
)

bot = Bot(token=TOKEN)

# ================= БАЗА =================
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.executescript("""
CREATE TABLE IF NOT EXISTS roles(peer INTEGER, uid INTEGER, lvl INTEGER, PRIMARY KEY(peer, uid));
CREATE TABLE IF NOT EXISTS bans(peer INTEGER, uid INTEGER, reason TEXT, admin INTEGER, ts INTEGER, PRIMARY KEY(peer, uid));
CREATE TABLE IF NOT EXISTS mutes(peer INTEGER, uid INTEGER, until INTEGER, PRIMARY KEY(peer, uid));
CREATE TABLE IF NOT EXISTS warns(id INTEGER PRIMARY KEY AUTOINCREMENT, peer INTEGER, uid INTEGER, reason TEXT, admin INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS settings(peer INTEGER, key TEXT, val TEXT, PRIMARY KEY(peer, key));
CREATE TABLE IF NOT EXISTS stats(peer INTEGER, uid INTEGER, cnt INTEGER DEFAULT 0, PRIMARY KEY(peer, uid));
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY AUTOINCREMENT, peer INTEGER, uid INTEGER, admin INTEGER, action TEXT, reason TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS badwords(peer INTEGER, word TEXT, PRIMARY KEY(peer, word));
CREATE TABLE IF NOT EXISTS notes(peer INTEGER, name TEXT, text TEXT, PRIMARY KEY(peer, name));
CREATE TABLE IF NOT EXISTS nicks(peer INTEGER, uid INTEGER, nick TEXT, PRIMARY KEY(peer, uid));
CREATE TABLE IF NOT EXISTS afk(uid INTEGER PRIMARY KEY, reason TEXT, ts INTEGER);
-- проектные (общие для всех бесед) --
CREATE TABLE IF NOT EXISTS orgs(name TEXT PRIMARY KEY, leader INTEGER, since INTEGER);
CREATE TABLE IF NOT EXISTS apps(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, role TEXT, text TEXT, ts INTEGER, status TEXT DEFAULT 'new', reviewer INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS duty(uid INTEGER PRIMARY KEY, since INTEGER);
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, org TEXT, text TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS vigs(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, reason TEXT, admin INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS rules(num TEXT PRIMARY KEY, text TEXT);
""")
db.commit()


def q(sql, args=()):
    cur = db.execute(sql, args)
    db.commit()
    return cur


def one(sql, args=()):
    return db.execute(sql, args).fetchone()


def rows(sql, args=()):
    return db.execute(sql, args).fetchall()


def get_set(peer, key):
    r = one("SELECT val FROM settings WHERE peer=? AND key=?", (peer, key))
    return r[0] if r else None


def set_set(peer, key, val):
    if val is None:
        q("DELETE FROM settings WHERE peer=? AND key=?", (peer, key))
    else:
        q("INSERT INTO settings(peer,key,val) VALUES(?,?,?) "
          "ON CONFLICT(peer,key) DO UPDATE SET val=excluded.val", (peer, key, val))


def gget(key):
    return get_set(0, key)


def gput(key, val):
    set_set(0, key, val)


def flag(peer, key):
    return get_set(peer, key) == "1"


def level(peer, uid):
    if uid in OWNERS:
        return 4
    r = one("SELECT lvl FROM roles WHERE peer=? AND uid=?", (peer, uid))
    return r[0] if r else 0


def max_warns(peer):
    v = get_set(peer, "maxwarns")
    return int(v) if v and v.isdigit() else MAX_WARNS


def log_action(peer, uid, admin, action, reason=""):
    q("INSERT INTO log(peer,uid,admin,action,reason,ts) VALUES(?,?,?,?,?,?)",
      (peer, uid, admin, action, reason, int(time.time())))


def find_org(name):
    n = name.strip().lower()
    for (x,) in rows("SELECT name FROM orgs"):
        if x.lower() == n:
            return x
    return None


def nkey(s):
    return [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", s)]


# ================= ХЕЛПЕРЫ =================
cache = {}


async def names(ids):
    need = [i for i in set(ids) if i > 0 and i not in cache]
    if need:
        try:
            for u in await bot.api.users.get(user_ids=need):
                cache[u.id] = f"{u.first_name} {u.last_name}"
        except Exception:
            pass
    return {i: cache.get(i, f"id{i}") for i in ids}


async def mention(uid):
    n = (await names([uid]))[uid]
    return f"[id{uid}|{n}]"


async def admin_label(uid):
    return "🤖 Автомодерация" if uid == 0 else await mention(uid)


async def say(m: Message, text):
    await m.answer(text, disable_mentions=True)


async def dm(uid, text):
    try:
        await bot.api.messages.send(user_id=uid, message=text, random_id=0)
        return True
    except Exception:
        return False


async def kick(peer, uid):
    try:
        await bot.api.messages.remove_chat_user(chat_id=peer - 2000000000, member_id=uid)
        return True
    except Exception:
        return False


async def delete_msg(peer, cmid):
    try:
        await bot.api.messages.delete(peer_id=peer, cmids=[cmid], delete_for_all=True)
    except Exception:
        pass


def parse_dur(s):
    r = re.fullmatch(r"(\d+)([mhdмчд]?)", s.lower())
    if not r:
        return None
    mult = {"": 60, "m": 60, "м": 60, "h": 3600, "ч": 3600, "d": 86400, "д": 86400}[r.group(2)]
    return min(int(r.group(1)) * mult, 30 * 86400)


def fmt_dur(sec):
    sec = int(sec)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    mi = r // 60
    p = []
    if d:
        p.append(f"{d} д.")
    if h:
        p.append(f"{h} ч.")
    if mi or not p:
        p.append(f"{max(mi, 1) if not p else mi} мин.")
    return " ".join(p)


def fmt_ts(ts):
    return datetime.fromtimestamp(ts, MSK).strftime("%d.%m.%Y %H:%M")


async def get_target(m: Message, a):
    """Возвращает (uid, остаток_аргументов)."""
    if m.reply_message and m.reply_message.from_id > 0:
        return m.reply_message.from_id, a
    if m.fwd_messages and m.fwd_messages[0].from_id > 0:
        return m.fwd_messages[0].from_id, a
    if not a:
        return None, a
    x = a[0]
    r = re.match(r"\[id(\d+)\|", x)
    if r:
        return int(r.group(1)), a[1:]
    if x.isdigit():
        return int(x), a[1:]
    short = x.rstrip("/").split("/")[-1]
    try:
        u = await bot.api.users.get(user_ids=[short])
        if u:
            return u[0].id, a[1:]
    except Exception:
        pass
    return None, a


async def victim(m: Message, a, check=True):
    uid, rest = await get_target(m, a)
    if not uid:
        await say(m, "❓ Укажи пользователя: ответом на сообщение, @упоминанием, ID или ссылкой.")
        return None, a
    if check:
        if uid == m.from_id:
            await say(m, "⛔ На себя нельзя.")
            return None, a
        if level(m.peer_id, uid) >= level(m.peer_id, m.from_id):
            await say(m, "⛔ Роль цели не ниже твоей.")
            return None, a
    return uid, rest


async def chat_members(peer):
    try:
        return await bot.api.messages.get_conversation_members(peer_id=peer, fields=["online"])
    except Exception:
        return None


async def tag_all(m: Message, head):
    r = await chat_members(m.peer_id)
    if not r:
        return False
    ids = [i.member_id for i in r.items if i.member_id and i.member_id > 0 and i.member_id != m.from_id]
    if not ids:
        await m.answer(head)
        return True
    for i in range(0, len(ids), 50):
        chunk = "".join(f"[id{u}|{ZW}]" for u in ids[i:i + 50])
        await m.answer((head + "\n" if i == 0 else "") + chunk)
    return True


def staff_ids(peer):
    return [u for (u,) in rows("SELECT uid FROM roles WHERE peer=? AND lvl>=1", (peer,))]


async def add_warn(m: Message, uid, reason, admin):
    peer = m.peer_id
    q("INSERT INTO warns(peer,uid,reason,admin,ts) VALUES(?,?,?,?,?)",
      (peer, uid, reason, admin, int(time.time())))
    log_action(peer, uid, admin, "warn", reason)
    n = one("SELECT COUNT(*) FROM warns WHERE peer=? AND uid=?", (peer, uid))[0]
    mx = max_warns(peer)
    text = (f"⚠️ {await mention(uid)} получил варн ({n}/{mx}).\n"
            f"👮 Выдал: {await admin_label(admin)}\n📝 Причина: {reason}")
    if n >= mx:
        q("DELETE FROM warns WHERE peer=? AND uid=?", (peer, uid))
        await kick(peer, uid)
        log_action(peer, uid, admin, "kick", "лимит варнов")
        text += "\n🚫 Лимит варнов — исключён из беседы."
    await say(m, text)


# ================= РЕГИСТРАЦИЯ КОМАНД =================
COMMANDS = {}


def cmd(*cmd_names, lvl=0):
    def deco(fn):
        async def wrapped(m, a, rest):
            if lvl and level(m.peer_id, m.from_id) < lvl:
                return await say(m, f"⛔ Нужна роль: {ROLES[lvl]} или выше.")
            await fn(m, a, rest)
        for n in cmd_names:
            COMMANDS[n] = wrapped
        return fn
    return deco


HELP = [
    f"""📋 {PROJECT} — КОМАНДЫ (префикс / или !)

👤 ДЛЯ ВСЕХ:
/help — меню
/about — о проекте
/ip — адрес сервера
/launcher — лаунчеры и кэш
/release — сколько до релиза
/rule N — пункт правил сервера
/rulelist — все пункты правил
/leaders — лидеры организаций
/duties — кто на дежурстве
/apply должность | текст — заявка в команду
/vigs — свои выговоры
/rules — правила чата
/staff — руководство
/info [юзер] — карточка
/stats [юзер] — статистика
/top — топ по сообщениям
/warns [юзер] — варны
/id — твой ID и ID беседы
/nick текст — ник (/nick - убрать)
/nicks — ники беседы
/afk [причина] — уйти в AFK
/report [текст] — жалоба (лучше ответом)
/adm — позвать модераторов
/note название, /notes — заметки
/time, /ping

🎲 РАЗВЛЕЧЕНИЯ:
/roll [N], /coin, /choose а | б | в
/calc выражение, /who текст
/rate текст, /ball вопрос""",
    """🛡 ХЕЛПЕР+:
/kick [юзер] [причина]
/mute [юзер] [время] [причина]
/unmute, /mutelist
/warn [юзер] [причина], /unwarn
/history [юзер] — история наказаний
/del — удалить сообщение (ответом)
/pin, /unpin — закреп (ответом)
/note add название текст
/note del название
/zov [текст] — упомянуть всех
/online — кто онлайн
/duty on|off — встать/сойти с дежурства

👮 АДМИНИСТРАТОР+:
/ban [юзер] [причина], /unban, /banlist
/clearwarns [юзер] — снять все варны
/unmuteall — снять все муты
/purge N — удалить последние N сообщений
/quiet on|off — режим тишины
/antilink on|off — удалять ссылки + варн
/antispam on|off — флуд = мут 5 мин
/antimat on|off — стоп-слова + варн
/slowmode N — пауза между сообщениями (сек)
/addword слово, /delword слово, /words
/kickdog — кик удалённых/заблокированных
/settings — настройки беседы
/apps — новые заявки в команду
/app N — просмотр заявки
/accept N — принять заявку
/deny N [причина] — отклонить
/otchets [организация] — отчёты лидеров""",
    """👑 ГЛАВНЫЙ АДМИНИСТРАТОР+:
/setrole [юзер] [0-3] — роль в беседе
/setrules текст — правила беседы
/setwelcome текст|off|default
 ({name} — имя вошедшего, {project} — проект)
/setwarns N — лимит варнов (1-10)
/settitle название — название беседы
/announce текст — объявление с призывом всех

📌 ПРОЕКТ:
/setip адрес — адрес сервера
/setlauncher pc|mobile|cache ссылка
/setrelease ДД.ММ.ГГГГ|off — дата релиза
/setabout текст|default — текст /about
/addrule N текст — добавить пункт правил
/delrule N — удалить пункт

🏢 ОРГАНИЗАЦИИ:
/addorg название — добавить организацию
/delorg название — удалить организацию
/setleader [юзер] организация — назначить лидера
/delleader организация — снять лидера
/vig [юзер] причина — выговор лидеру/админу
/unvig [юзер] — снять последний выговор

📝 ЛИДЕРАМ:
/otchet текст — отчёт (только лидеры организаций)

⏱ Время: 30, 30m, 2h, 1d (число без буквы = минуты).
👤 Юзер: ответом, @упоминанием, ID или ссылкой.""",
]


# ================= ОБЩИЕ =================
@cmd("help", "помощь", "start", "команды")
async def c_help(m, a, rest):
    for part in HELP:
        await say(m, part)


@cmd("id")
async def c_id(m, a, rest):
    await say(m, f"🆔 Твой ID: {m.from_id}\n💬 ID беседы: {m.peer_id}")


@cmd("ping", "пинг")
async def c_ping(m, a, rest):
    await say(m, f"🏓 Понг! Аптайм: {fmt_dur(time.time() - START)}")


@cmd("time", "время")
async def c_time(m, a, rest):
    await say(m, "🕒 " + datetime.now(MSK).strftime("%d.%m.%Y %H:%M:%S") + " (МСК)")


@cmd("rules", "правила")
async def c_rules(m, a, rest):
    await say(m, get_set(m.peer_id, "rules") or "📜 Правила беседы ещё не заданы. Главный администратор: /setrules текст")


@cmd("setrules", lvl=3)
async def c_setrules(m, a, rest):
    if not rest:
        return await say(m, "Использование: /setrules текст правил")
    set_set(m.peer_id, "rules", rest)
    await say(m, "✅ Правила беседы обновлены.")


@cmd("setwelcome", lvl=3)
async def c_setwelcome(m, a, rest):
    if not rest:
        return await say(m, "Использование: /setwelcome текст | off | default\n{name} — имя вошедшего, {project} — проект")
    low = rest.lower()
    if low == "off":
        set_set(m.peer_id, "welcome", "off")
        return await say(m, "✅ Приветствие отключено.")
    if low == "default":
        set_set(m.peer_id, "welcome", None)
        return await say(m, "✅ Возвращено приветствие по умолчанию.")
    set_set(m.peer_id, "welcome", rest)
    await say(m, "✅ Приветствие обновлено.")


@cmd("settitle", "название", lvl=3)
async def c_settitle(m, a, rest):
    if not rest:
        return await say(m, "Использование: /settitle новое название")
    try:
        await bot.api.messages.edit_chat(chat_id=m.peer_id - 2000000000, title=rest[:80])
    except Exception:
        await say(m, "⚠️ Не вышло. Бот должен быть админом беседы.")


@cmd("setwarns", lvl=3)
async def c_setwarns(m, a, rest):
    if not a or not a[0].isdigit() or not (1 <= int(a[0]) <= 10):
        return await say(m, "Использование: /setwarns 1-10")
    set_set(m.peer_id, "maxwarns", a[0])
    await say(m, f"✅ Лимит варнов: {a[0]}")


@cmd("settings", "настройки", lvl=2)
async def c_settings(m, a, rest):
    p = m.peer_id

    def st(k):
        return "✅" if flag(p, k) else "❌"

    sm = get_set(p, "slowmode") or "0"
    wl = get_set(p, "welcome")
    wl_txt = "выкл" if wl == "off" else ("свой" if wl else "по умолчанию")
    await say(m, (
        f"⚙️ Настройки беседы ({PROJECT}):\n"
        f"🤫 Режим тишины: {st('quiet')}\n"
        f"🔗 Анти-ссылки: {st('antilink')}\n"
        f"💥 Антиспам: {st('antispam')}\n"
        f"🤬 Антимат: {st('antimat')} (слов: {one('SELECT COUNT(*) FROM badwords WHERE peer=?', (p,))[0]})\n"
        f"🐢 Slowmode: {sm} сек.\n"
        f"⚠️ Лимит варнов: {max_warns(p)}\n"
        f"👋 Приветствие: {wl_txt}\n"
        f"📜 Правила беседы: {'есть' if get_set(p, 'rules') else 'нет'}"
    ))


# ================= ПРОЕКТ =================
@cmd("about", "проект", "оздании")
async def c_about(m, a, rest):
    await say(m, gget("about") or DEFAULT_ABOUT)


@cmd("setabout", lvl=3)
async def c_setabout(m, a, rest):
    if not rest:
        return await say(m, "Использование: /setabout текст | default")
    if rest.lower() == "default":
        gput("about", None)
        return await say(m, "✅ Возвращён текст по умолчанию.")
    gput("about", rest)
    await say(m, "✅ Текст /about обновлён.")


@cmd("ip", "адрес", "сервер")
async def c_ip(m, a, rest):
    v = gget("ip")
    await say(m, f"🌐 Адрес сервера {PROJECT}: {v}" if v else "Адрес сервера ещё не добавлен.")


@cmd("setip", lvl=3)
async def c_setip(m, a, rest):
    if not rest:
        return await say(m, "Использование: /setip ip:порт")
    gput("ip", rest)
    await say(m, "✅ Адрес сохранён.")


@cmd("launcher", "лаунчер", "скачать", "кэш", "кеш")
async def c_launcher(m, a, rest):
    def v(k):
        return gget(k) or "ссылка ещё не добавлена"
    await say(m, (
        f"📥 {PROJECT} — загрузки:\n"
        f"🖥 Лаунчер ПК: {v('launcher_pc')}\n"
        f"📱 Лаунчер Android: {v('launcher_mobile')}\n"
        f"📦 Кэш игры: {v('cache')}"
    ))


@cmd("setlauncher", lvl=3)
async def c_setlauncher(m, a, rest):
    keys = {"pc": "launcher_pc", "пк": "launcher_pc",
            "mobile": "launcher_mobile", "android": "launcher_mobile", "мобайл": "launcher_mobile",
            "cache": "cache", "кэш": "cache", "кеш": "cache"}
    if len(a) < 2 or a[0].lower() not in keys:
        return await say(m, "Использование: /setlauncher pc|mobile|cache ссылка")
    gput(keys[a[0].lower()], a[1])
    await say(m, "✅ Ссылка сохранена.")


@cmd("release", "релиз")
async def c_release(m, a, rest):
    r = gget("release")
    if not r:
        return await say(m, f"📅 Дата релиза {PROJECT} пока не объявлена.")
    d = datetime.strptime(r, "%Y-%m-%d").date()
    delta = (d - datetime.now(MSK).date()).days
    ds = d.strftime("%d.%m.%Y")
    if delta > 0:
        await say(m, f"📅 До релиза {PROJECT}: {delta} дн. (дата: {ds})")
    elif delta == 0:
        await say(m, f"🎉 Релиз {PROJECT} — сегодня ({ds})!")
    else:
        await say(m, f"✅ Релиз {PROJECT} состоялся {ds}.")


@cmd("setrelease", lvl=3)
async def c_setrelease(m, a, rest):
    if not a:
        return await say(m, "Использование: /setrelease ДД.ММ.ГГГГ | off")
    if a[0].lower() == "off":
        gput("release", None)
        return await say(m, "✅ Дата релиза убрана.")
    try:
        d = datetime.strptime(a[0], "%d.%m.%Y")
    except ValueError:
        return await say(m, "⛔ Формат даты: ДД.ММ.ГГГГ")
    gput("release", d.strftime("%Y-%m-%d"))
    await say(m, f"✅ Дата релиза: {a[0]}")


@cmd("announce", "объявление", lvl=3)
async def c_announce(m, a, rest):
    if not rest:
        return await say(m, "Использование: /announce текст")
    ok = await tag_all(m, f"📣 ОБЪЯВЛЕНИЕ {PROJECT}\n\n{rest}\n\n— {await mention(m.from_id)}")
    if not ok:
        await say(m, "⚠️ Не могу получить участников. Бот должен быть админом беседы.")


# ================= ПРАВИЛА СЕРВЕРА =================
@cmd("rule", "пункт")
async def c_rule(m, a, rest):
    if not a:
        return await say(m, "Использование: /rule номер (например /rule 2.1). Все пункты: /rulelist")
    r = one("SELECT text FROM rules WHERE num=?", (a[0],))
    await say(m, f"📖 Пункт {a[0]}: {r[0]}" if r else "❌ Такого пункта нет. Список: /rulelist")


@cmd("rulelist", "пункты")
async def c_rulelist(m, a, rest):
    r = sorted(rows("SELECT num,text FROM rules"), key=lambda x: nkey(x[0]))
    if not r:
        return await say(m, "Пункты правил ещё не добавлены.")
    lines = [f"📖 Правила {PROJECT}:"] + [f"{n} — {t[:80]}" for n, t in r]
    buf = ""
    for ln in lines:
        if len(buf) + len(ln) > 3500:
            await say(m, buf)
            buf = ""
        buf += ln + "\n"
    if buf:
        await say(m, buf)


@cmd("addrule", lvl=3)
async def c_addrule(m, a, rest):
    parts = rest.split(None, 1)
    if len(parts) < 2:
        return await say(m, "Использование: /addrule номер текст (например /addrule 2.1 NonRP — запрещён)")
    q("INSERT OR REPLACE INTO rules(num,text) VALUES(?,?)", (parts[0], parts[1]))
    await say(m, f"✅ Пункт {parts[0]} сохранён.")


@cmd("delrule", lvl=3)
async def c_delrule(m, a, rest):
    if not a:
        return await say(m, "Использование: /delrule номер")
    n = q("DELETE FROM rules WHERE num=?", (a[0],)).rowcount
    await say(m, "✅ Удалено." if n else "❌ Такого пункта нет.")


# ================= ОРГАНИЗАЦИИ / ЛИДЕРЫ =================
@cmd("leaders", "лидеры")
async def c_leaders(m, a, rest):
    r = rows("SELECT name,leader FROM orgs ORDER BY name")
    if not r:
        return await say(m, "Организации ещё не добавлены.")
    nm = await names([l for _, l in r if l])
    lines = [f"🏢 Лидеры {PROJECT}:"]
    for name, l in r:
        lines.append(f"• {name} — " + (f"[id{l}|{nm[l]}]" if l else "вакантно"))
    await say(m, "\n".join(lines))


@cmd("addorg", lvl=3)
async def c_addorg(m, a, rest):
    if not rest:
        return await say(m, "Использование: /addorg название организации")
    if find_org(rest):
        return await say(m, "Такая организация уже есть.")
    q("INSERT INTO orgs(name,leader,since) VALUES(?,NULL,NULL)", (rest.strip(),))
    await say(m, f"✅ Организация «{rest.strip()}» добавлена.")


@cmd("delorg", lvl=3)
async def c_delorg(m, a, rest):
    org = find_org(rest) if rest else None
    if not org:
        return await say(m, "❌ Организация не найдена. Список: /leaders")
    q("DELETE FROM orgs WHERE name=?", (org,))
    await say(m, f"✅ Организация «{org}» удалена.")


@cmd("setleader", "лидер", lvl=3)
async def c_setleader(m, a, rest):
    uid, a = await victim(m, a, check=False)
    if not uid:
        return
    name = " ".join(a).strip()
    if not name:
        return await say(m, "Использование: /setleader [юзер] организация")
    org = find_org(name)
    if not org:
        q("INSERT INTO orgs(name,leader,since) VALUES(?,NULL,NULL)", (name,))
        org = name
    q("UPDATE orgs SET leader=?, since=? WHERE name=?", (uid, int(time.time()), org))
    log_action(m.peer_id, uid, m.from_id, "setleader", org)
    await say(m, f"✅ {await mention(uid)} назначен лидером: {org}")


@cmd("delleader", "снятьлидера", lvl=3)
async def c_delleader(m, a, rest):
    org = find_org(rest) if rest else None
    if not org:
        return await say(m, "Использование: /delleader организация (список: /leaders)")
    r = one("SELECT leader FROM orgs WHERE name=?", (org,))
    q("UPDATE orgs SET leader=NULL, since=NULL WHERE name=?", (org,))
    if r and r[0]:
        log_action(m.peer_id, r[0], m.from_id, "delleader", org)
    await say(m, f"✅ Лидер организации «{org}» снят.")


@cmd("otchet", "отчёт", "отчет")
async def c_otchet(m, a, rest):
    r = one("SELECT name FROM orgs WHERE leader=?", (m.from_id,))
    if not r and level(m.peer_id, m.from_id) < 3:
        return await say(m, "⛔ Отчёты подают только лидеры организаций.")
    if not rest:
        return await say(m, "Использование: /otchet текст отчёта")
    org = r[0] if r else "—"
    cur = q("INSERT INTO reports(uid,org,text,ts) VALUES(?,?,?,?)", (m.from_id, org, rest, int(time.time())))
    await say(m, f"✅ Отчёт №{cur.lastrowid} принят ({org}).")


@cmd("otchets", "отчёты", "отчеты", lvl=2)
async def c_otchets(m, a, rest):
    if rest:
        org = find_org(rest)
        if not org:
            return await say(m, "❌ Организация не найдена.")
        r = rows("SELECT id,uid,org,text,ts FROM reports WHERE org=? ORDER BY id DESC LIMIT 8", (org,))
    else:
        r = rows("SELECT id,uid,org,text,ts FROM reports ORDER BY id DESC LIMIT 8")
    if not r:
        return await say(m, "Отчётов нет.")
    nm = await names([u for _, u, _, _, _ in r])
    out = ["📝 Последние отчёты:"]
    for i, u, org, t, ts in r:
        out.append(f"\n№{i} • {org} • [id{u}|{nm[u]}] • {fmt_ts(ts)}\n{t[:300]}")
    await say(m, "\n".join(out))


# ================= ВЫГОВОРЫ =================
@cmd("vig", "выговор", lvl=3)
async def c_vig(m, a, rest):
    uid, a = await victim(m, a)
    if not uid:
        return
    reason = " ".join(a) or "не указана"
    q("INSERT INTO vigs(uid,reason,admin,ts) VALUES(?,?,?,?)", (uid, reason, m.from_id, int(time.time())))
    n = one("SELECT COUNT(*) FROM vigs WHERE uid=?", (uid,))[0]
    log_action(m.peer_id, uid, m.from_id, "vig", reason)
    text = (f"📛 {await mention(uid)} получил выговор ({n}/{MAX_VIGS}).\n"
            f"👮 Выдал: {await mention(m.from_id)}\n📝 Причина: {reason}")
    if n >= MAX_VIGS:
        text += "\n❗ Достигнут лимит выговоров — требуется рассмотрение снятия с должности."
    await say(m, text)


@cmd("unvig", "снятьвыговор", lvl=3)
async def c_unvig(m, a, rest):
    uid, _ = await victim(m, a, check=False)
    if not uid:
        return
    r = one("SELECT id FROM vigs WHERE uid=? ORDER BY id DESC LIMIT 1", (uid,))
    if not r:
        return await say(m, "У пользователя нет выговоров.")
    q("DELETE FROM vigs WHERE id=?", (r[0],))
    log_action(m.peer_id, uid, m.from_id, "unvig")
    n = one("SELECT COUNT(*) FROM vigs WHERE uid=?", (uid,))[0]
    await say(m, f"✅ Выговор снят с {await mention(uid)} ({n}/{MAX_VIGS}).")


@cmd("vigs", "выговоры")
async def c_vigs(m, a, rest):
    uid, _ = await get_target(m, a)
    uid = uid or m.from_id
    if uid != m.from_id and level(m.peer_id, m.from_id) < 2:
        return await say(m, "⛔ Чужие выговоры видят администраторы и выше.")
    r = rows("SELECT reason,admin,ts FROM vigs WHERE uid=? ORDER BY id", (uid,))
    if not r:
        return await say(m, f"У {await mention(uid)} нет выговоров.")
    lines = [f"📛 Выговоры {await mention(uid)} ({len(r)}/{MAX_VIGS}):"]
    for i, (rs, adm, ts) in enumerate(r, 1):
        lines.append(f"{i}. {rs} — {await mention(adm)} ({fmt_ts(ts)})")
    await say(m, "\n".join(lines))


# ================= ДЕЖУРСТВА =================
@cmd("duty", "дежурство", lvl=1)
async def c_duty(m, a, rest):
    if not a or a[0].lower() not in ("on", "off", "вкл", "выкл"):
        return await say(m, "Использование: /duty on|off")
    if a[0].lower() in ("on", "вкл"):
        q("INSERT OR REPLACE INTO duty(uid,since) VALUES(?,?)", (m.from_id, int(time.time())))
        await say(m, f"🟢 {await mention(m.from_id)} заступил на дежурство.")
    else:
        r = one("SELECT since FROM duty WHERE uid=?", (m.from_id,))
        q("DELETE FROM duty WHERE uid=?", (m.from_id,))
        extra = f" Отдежурил: {fmt_dur(time.time() - r[0])}." if r else ""
        await say(m, f"🔴 {await mention(m.from_id)} закончил дежурство.{extra}")


@cmd("duties", "дежурные")
async def c_duties(m, a, rest):
    r = rows("SELECT uid,since FROM duty ORDER BY since")
    if not r:
        return await say(m, "Сейчас никто не дежурит.")
    nm = await names([u for u, _ in r])
    await say(m, "🟢 На дежурстве:\n" + "\n".join(
        f"• [id{u}|{nm[u]}] — {fmt_dur(time.time() - s)}" for u, s in r))


# ================= ЗАЯВКИ В КОМАНДУ =================
@cmd("apply", "заявка")
async def c_apply(m, a, rest):
    if not rest:
        return await say(m, (f"📨 Набор в команду {PROJECT}.\nИспользование: /apply должность | текст заявки\n"
                             "Пример: /apply разработчик | 20 лет, пишу на Lua и C++, опыт 3 года"))
    if "|" in rest:
        role, text = [x.strip() for x in rest.split("|", 1)]
    else:
        parts = rest.split(None, 1)
        role, text = parts[0], (parts[1] if len(parts) > 1 else "")
    if not role or len(text) < 10:
        return await say(m, "⛔ Укажи должность и расскажи о себе (минимум 10 символов).")
    if one("SELECT id FROM apps WHERE uid=? AND status='new'", (m.from_id,)):
        return await say(m, "⛔ У тебя уже есть заявка на рассмотрении.")
    cur = q("INSERT INTO apps(uid,role,text,ts) VALUES(?,?,?,?)", (m.from_id, role[:60], text[:1500], int(time.time())))
    staff = staff_ids(m.peer_id)
    tags = "".join(f"[id{u}|{ZW}]" for u in staff)
    await m.answer(f"📨 Заявка №{cur.lastrowid} от {await mention(m.from_id)} принята.\n"
                   f"Должность: {role[:60]}\nРассмотрят администраторы." + (f"\n{tags}" if tags else ""))


@cmd("apps", "заявки", lvl=2)
async def c_apps(m, a, rest):
    r = rows("SELECT id,uid,role,ts FROM apps WHERE status='new' ORDER BY id LIMIT 25")
    if not r:
        return await say(m, "Новых заявок нет.")
    nm = await names([u for _, u, _, _ in r])
    await say(m, "📨 Новые заявки:\n" + "\n".join(
        f"№{i} — [id{u}|{nm[u]}] — {role} ({fmt_ts(ts)})" for i, u, role, ts in r) + "\n\nПросмотр: /app N")


@cmd("app", "заявка_просмотр", lvl=2)
async def c_app(m, a, rest):
    if not a or not a[0].isdigit():
        return await say(m, "Использование: /app N")
    r = one("SELECT id,uid,role,text,ts,status,reviewer,note FROM apps WHERE id=?", (int(a[0]),))
    if not r:
        return await say(m, "❌ Заявка не найдена.")
    i, uid, role, text, ts, st, rv, note = r
    stt = {"new": "новая", "accepted": "принята", "denied": "отклонена"}.get(st, st)
    out = [f"📨 Заявка №{i}", f"👤 {await mention(uid)}", f"🎯 Должность: {role}",
           f"📅 {fmt_ts(ts)}", f"📌 Статус: {stt}", f"\n{text}"]
    if rv:
        out.append(f"\nРассмотрел: {await mention(rv)}" + (f"\nКомментарий: {note}" if note else ""))
    await say(m, "\n".join(out))


async def review_app(m, a, rest, status):
    if not a or not a[0].isdigit():
        return await say(m, f"Использование: /{'accept' if status == 'accepted' else 'deny'} N" +
                         ("" if status == "accepted" else " [причина]"))
    n = int(a[0])
    r = one("SELECT uid,status FROM apps WHERE id=?", (n,))
    if not r:
        return await say(m, "❌ Заявка не найдена.")
    if r[1] != "new":
        return await say(m, "⛔ Заявка уже рассмотрена.")
    note = " ".join(a[1:])
    q("UPDATE apps SET status=?, reviewer=?, note=? WHERE id=?", (status, m.from_id, note, n))
    uid = r[0]
    if status == "accepted":
        await say(m, f"✅ Заявка №{n} принята. Кандидат: {await mention(uid)}")
        await dm(uid, f"{PROJECT}: ваша заявка №{n} принята. С вами свяжется руководство.")
    else:
        await say(m, f"❌ Заявка №{n} отклонена. Кандидат: {await mention(uid)}" + (f"\nПричина: {note}" if note else ""))
        await dm(uid, f"{PROJECT}: ваша заявка №{n} отклонена." + (f" Причина: {note}" if note else ""))


@cmd("accept", "принять", lvl=2)
async def c_accept(m, a, rest):
    await review_app(m, a, rest, "accepted")


@cmd("deny", "отклонить", lvl=2)
async def c_deny(m, a, rest):
    await review_app(m, a, rest, "denied")


# ================= РОЛИ / ИНФО =================
@cmd("staff", "админы", "руководство")
async def c_staff(m, a, rest):
    peer = m.peer_id
    items = {u: l for u, l in rows("SELECT uid,lvl FROM roles WHERE peer=?", (peer,))}
    for o in OWNERS:
        items[o] = 4
    if not items:
        return await say(m, "Руководство не назначено.")
    nm = await names(list(items.keys()))
    out = [f"👥 Руководство {PROJECT}:"]
    for lv in (4, 3, 2, 1):
        ids = [u for u, l in items.items() if l == lv]
        if ids:
            out.append(f"\n{ROLES[lv]}:")
            out += [f"• [id{u}|{nm[u]}]" for u in ids]
    await say(m, "\n".join(out))


@cmd("setrole", "роль", lvl=3)
async def c_setrole(m, a, rest):
    uid, a = await victim(m, a)
    if not uid:
        return
    if not a or not a[0].isdigit() or not (0 <= int(a[0]) <= 3):
        return await say(m, "Использование: /setrole [юзер] [0-3]\n0 — снять, 1 — хелпер, 2 — администратор, 3 — главный администратор")
    lv = int(a[0])
    if lv >= level(m.peer_id, m.from_id):
        return await say(m, "⛔ Нельзя выдать роль не ниже своей.")
    if lv == 0:
        q("DELETE FROM roles WHERE peer=? AND uid=?", (m.peer_id, uid))
    else:
        q("INSERT OR REPLACE INTO roles(peer,uid,lvl) VALUES(?,?,?)", (m.peer_id, uid, lv))
    log_action(m.peer_id, uid, m.from_id, "setrole", ROLES[lv])
    await say(m, f"✅ {await mention(uid)} теперь: {ROLES[lv]}")


@cmd("info", "инфо")
async def c_info(m, a, rest):
    uid, _ = await get_target(m, a)
    uid = uid or m.from_id
    peer = m.peer_id
    w = one("SELECT COUNT(*) FROM warns WHERE peer=? AND uid=?", (peer, uid))[0]
    s = one("SELECT cnt FROM stats WHERE peer=? AND uid=?", (peer, uid))
    mu = one("SELECT until FROM mutes WHERE peer=? AND uid=?", (peer, uid))
    ban = one("SELECT reason FROM bans WHERE peer=? AND uid=?", (peer, uid))
    nk = one("SELECT nick FROM nicks WHERE peer=? AND uid=?", (peer, uid))
    lo = one("SELECT name FROM orgs WHERE leader=?", (uid,))
    lines = [
        f"👤 {await mention(uid)}",
        f"🆔 {uid}",
        f"🎖 Роль: {ROLES[level(peer, uid)]}",
        f"⚠️ Варны: {w}/{max_warns(peer)}",
        f"💬 Сообщений: {s[0] if s else 0}",
    ]
    if nk:
        lines.insert(2, f"🏷 Ник: {nk[0]}")
    if lo:
        lines.append(f"🏢 Лидер: {lo[0]}")
    if one("SELECT 1 FROM duty WHERE uid=?", (uid,)):
        lines.append("🟢 На дежурстве")
    if mu and mu[0] > time.time():
        lines.append(f"🔇 Мут до {fmt_ts(mu[0])}")
    if ban:
        lines.append(f"🚫 В бане: {ban[0]}")
    if one("SELECT 1 FROM afk WHERE uid=?", (uid,)):
        lines.append("💤 Сейчас в AFK")
    await say(m, "\n".join(lines))


@cmd("stats", "стата", "статистика")
async def c_stats(m, a, rest):
    uid, _ = await get_target(m, a)
    uid = uid or m.from_id
    peer = m.peer_id
    r = one("SELECT cnt FROM stats WHERE peer=? AND uid=?", (peer, uid))
    cnt = r[0] if r else 0
    place = one("SELECT COUNT(*)+1 FROM stats WHERE peer=? AND cnt>?", (peer, cnt))[0]
    total = one("SELECT COUNT(*) FROM stats WHERE peer=?", (peer,))[0]
    await say(m, f"📊 {await mention(uid)}\n💬 Сообщений: {cnt}\n🏅 Место: {place} из {total}")


@cmd("top", "топ")
async def c_top(m, a, rest):
    r = rows("SELECT uid,cnt FROM stats WHERE peer=? ORDER BY cnt DESC LIMIT 10", (m.peer_id,))
    if not r:
        return await say(m, "Статистики пока нет.")
    nm = await names([u for u, _ in r])
    await say(m, "🏆 Топ по сообщениям:\n" + "\n".join(
        f"{i}. [id{u}|{nm[u]}] — {c}" for i, (u, c) in enumerate(r, 1)))


@cmd("history", "история", lvl=1)
async def c_history(m, a, rest):
    uid, _ = await get_target(m, a)
    if not uid:
        return await say(m, "❓ Укажи пользователя.")
    r = rows("SELECT action,reason,admin,ts FROM log WHERE peer=? AND uid=? ORDER BY id DESC LIMIT 10",
             (m.peer_id, uid))
    if not r:
        return await say(m, "История чиста.")
    lines = [f"📚 История {await mention(uid)}:"]
    for act, rs, adm, ts in r:
        lines.append(f"• {fmt_ts(ts)} — {act}" + (f" ({rs})" if rs else "") + f" — {await admin_label(adm)}")
    await say(m, "\n".join(lines))


# ================= НИКИ / AFK =================
@cmd("nick", "ник")
async def c_nick(m, a, rest):
    peer = m.peer_id
    target = m.from_id
    if m.reply_message and m.reply_message.from_id > 0 and level(peer, m.from_id) >= 1:
        target = m.reply_message.from_id
    if not rest:
        return await say(m, "Использование: /nick текст (или /nick - чтобы убрать)")
    if target != m.from_id and level(peer, target) >= level(peer, m.from_id):
        return await say(m, "⛔ Роль цели не ниже твоей.")
    if rest == "-":
        q("DELETE FROM nicks WHERE peer=? AND uid=?", (peer, target))
        return await say(m, f"✅ Ник {await mention(target)} убран.")
    if len(rest) > 32:
        return await say(m, "⛔ Ник до 32 символов.")
    q("INSERT OR REPLACE INTO nicks(peer,uid,nick) VALUES(?,?,?)", (peer, target, rest))
    await say(m, f"✅ Ник {await mention(target)}: {rest}")


@cmd("nicks", "ники")
async def c_nicks(m, a, rest):
    r = rows("SELECT uid,nick FROM nicks WHERE peer=? LIMIT 50", (m.peer_id,))
    if not r:
        return await say(m, "Ников пока нет.")
    nm = await names([u for u, _ in r])
    await say(m, "🏷 Ники:\n" + "\n".join(f"• {n} — [id{u}|{nm[u]}]" for u, n in r))


@cmd("afk", "афк")
async def c_afk(m, a, rest):
    q("INSERT OR REPLACE INTO afk(uid,reason,ts) VALUES(?,?,?)",
      (m.from_id, rest or "без причины", int(time.time())))
    await say(m, f"💤 {await mention(m.from_id)} ушёл в AFK: {rest or 'без причины'}")


# ================= ЗАМЕТКИ =================
@cmd("note", "заметка")
async def c_note(m, a, rest):
    peer = m.peer_id
    if not a:
        return await say(m, "Использование: /note название | /note add название текст | /note del название")
    sub = a[0].lower()
    if sub == "add":
        if level(peer, m.from_id) < 1:
            return await say(m, f"⛔ Нужна роль: {ROLES[1]} или выше.")
        parts = rest.split(None, 2)
        if len(parts) < 3:
            return await say(m, "Использование: /note add название текст")
        q("INSERT OR REPLACE INTO notes(peer,name,text) VALUES(?,?,?)", (peer, parts[1].lower(), parts[2]))
        return await say(m, f"✅ Заметка «{parts[1].lower()}» сохранена.")
    if sub in ("del", "удалить"):
        if level(peer, m.from_id) < 1:
            return await say(m, f"⛔ Нужна роль: {ROLES[1]} или выше.")
        if len(a) < 2:
            return await say(m, "Использование: /note del название")
        q("DELETE FROM notes WHERE peer=? AND name=?", (peer, a[1].lower()))
        return await say(m, "✅ Удалено.")
    r = one("SELECT text FROM notes WHERE peer=? AND name=?", (peer, sub))
    await say(m, r[0] if r else "❌ Нет такой заметки. Список: /notes")


@cmd("notes", "заметки")
async def c_notes(m, a, rest):
    r = rows("SELECT name FROM notes WHERE peer=? ORDER BY name", (m.peer_id,))
    if not r:
        return await say(m, "Заметок нет.")
    await say(m, "📝 Заметки: " + ", ".join(x[0] for x in r))


# ================= МОДЕРАЦИЯ =================
@cmd("kick", "кик", lvl=1)
async def c_kick(m, a, rest):
    uid, a = await victim(m, a)
    if not uid:
        return
    ok = await kick(m.peer_id, uid)
    reason = " ".join(a) or "не указана"
    if ok:
        log_action(m.peer_id, uid, m.from_id, "kick", reason)
        await say(m, f"👢 {await mention(uid)} исключён.\n👮 Админ: {await mention(m.from_id)}\n📝 Причина: {reason}")
    else:
        await say(m, "⚠️ Не получилось. Бот должен быть админом беседы, а цель — не админом.")


@cmd("ban", "бан", lvl=2)
async def c_ban(m, a, rest):
    uid, a = await victim(m, a)
    if not uid:
        return
    reason = " ".join(a) or "не указана"
    q("INSERT OR REPLACE INTO bans(peer,uid,reason,admin,ts) VALUES(?,?,?,?,?)",
      (m.peer_id, uid, reason, m.from_id, int(time.time())))
    await kick(m.peer_id, uid)
    log_action(m.peer_id, uid, m.from_id, "ban", reason)
    await say(m, f"🚫 {await mention(uid)} забанен.\n👮 Админ: {await mention(m.from_id)}\n📝 Причина: {reason}")


@cmd("unban", "разбан", lvl=2)
async def c_unban(m, a, rest):
    uid, _ = await victim(m, a, check=False)
    if not uid:
        return
    q("DELETE FROM bans WHERE peer=? AND uid=?", (m.peer_id, uid))
    log_action(m.peer_id, uid, m.from_id, "unban")
    await say(m, f"✅ {await mention(uid)} разбанен.")


@cmd("banlist", "банлист", lvl=2)
async def c_banlist(m, a, rest):
    r = rows("SELECT uid,reason,ts FROM bans WHERE peer=? ORDER BY ts DESC LIMIT 30", (m.peer_id,))
    if not r:
        return await say(m, "Банлист пуст.")
    nm = await names([u for u, _, _ in r])
    await say(m, "🚫 Банлист:\n" + "\n".join(
        f"• [id{u}|{nm[u]}] — {rs} ({fmt_ts(ts)})" for u, rs, ts in r))


@cmd("mute", "мут", lvl=1)
async def c_mute(m, a, rest):
    uid, a = await victim(m, a)
    if not uid:
        return
    sec = 1800
    if a:
        d = parse_dur(a[0])
        if d:
            sec = d
            a = a[1:]
    reason = " ".join(a) or "не указана"
    q("INSERT OR REPLACE INTO mutes(peer,uid,until) VALUES(?,?,?)",
      (m.peer_id, uid, int(time.time()) + sec))
    log_action(m.peer_id, uid, m.from_id, "mute", f"{fmt_dur(sec)}; {reason}")
    await say(m, f"🔇 {await mention(uid)} в муте на {fmt_dur(sec)}.\n👮 Админ: {await mention(m.from_id)}\n📝 Причина: {reason}")


@cmd("unmute", "размут", lvl=1)
async def c_unmute(m, a, rest):
    uid, _ = await victim(m, a, check=False)
    if not uid:
        return
    q("DELETE FROM mutes WHERE peer=? AND uid=?", (m.peer_id, uid))
    log_action(m.peer_id, uid, m.from_id, "unmute")
    await say(m, f"🔊 {await mention(uid)} размучен.")


@cmd("mutelist", "мутлист", lvl=1)
async def c_mutelist(m, a, rest):
    r = rows("SELECT uid,until FROM mutes WHERE peer=? AND until>? ORDER BY until", (m.peer_id, int(time.time())))
    if not r:
        return await say(m, "Активных мутов нет.")
    nm = await names([u for u, _ in r])
    await say(m, "🔇 В муте:\n" + "\n".join(f"• [id{u}|{nm[u]}] — до {fmt_ts(t)}" for u, t in r))


@cmd("unmuteall", lvl=2)
async def c_unmuteall(m, a, rest):
    n = q("DELETE FROM mutes WHERE peer=?", (m.peer_id,)).rowcount
    await say(m, f"🔊 Снято мутов: {n}")


@cmd("warn", "варн", "пред", lvl=1)
async def c_warn(m, a, rest):
    uid, a = await victim(m, a)
    if not uid:
        return
    await add_warn(m, uid, " ".join(a) or "не указана", m.from_id)


@cmd("unwarn", "анварн", lvl=1)
async def c_unwarn(m, a, rest):
    uid, _ = await victim(m, a, check=False)
    if not uid:
        return
    r = one("SELECT id FROM warns WHERE peer=? AND uid=? ORDER BY id DESC LIMIT 1", (m.peer_id, uid))
    if not r:
        return await say(m, "У пользователя нет варнов.")
    q("DELETE FROM warns WHERE id=?", (r[0],))
    log_action(m.peer_id, uid, m.from_id, "unwarn")
    n = one("SELECT COUNT(*) FROM warns WHERE peer=? AND uid=?", (m.peer_id, uid))[0]
    await say(m, f"✅ Варн снят с {await mention(uid)} ({n}/{max_warns(m.peer_id)}).")


@cmd("clearwarns", "очиститьварны", lvl=2)
async def c_clearwarns(m, a, rest):
    uid, _ = await victim(m, a, check=False)
    if not uid:
        return
    q("DELETE FROM warns WHERE peer=? AND uid=?", (m.peer_id, uid))
    log_action(m.peer_id, uid, m.from_id, "clearwarns")
    await say(m, f"✅ Все варны {await mention(uid)} сняты.")


@cmd("warns", "варны")
async def c_warns(m, a, rest):
    uid, _ = await get_target(m, a)
    uid = uid or m.from_id
    r = rows("SELECT reason,admin,ts FROM warns WHERE peer=? AND uid=? ORDER BY id", (m.peer_id, uid))
    if not r:
        return await say(m, f"У {await mention(uid)} нет варнов.")
    lines = [f"⚠️ Варны {await mention(uid)} ({len(r)}/{max_warns(m.peer_id)}):"]
    for i, (rs, adm, ts) in enumerate(r, 1):
        lines.append(f"{i}. {rs} — {await admin_label(adm)} ({fmt_ts(ts)})")
    await say(m, "\n".join(lines))


@cmd("del", "удалить", lvl=1)
async def c_del(m, a, rest):
    if not m.reply_message:
        return await say(m, "Ответь командой на сообщение, которое нужно удалить.")
    await delete_msg(m.peer_id, m.reply_message.conversation_message_id)
    await delete_msg(m.peer_id, m.conversation_message_id)


@cmd("purge", "чистка", lvl=2)
async def c_purge(m, a, rest):
    if not a or not a[0].isdigit():
        return await say(m, "Использование: /purge N (до 100)")
    n = min(int(a[0]), 100)
    try:
        h = await bot.api.messages.get_history(peer_id=m.peer_id, count=n + 1)
        cmids = [x.conversation_message_id for x in h.items if x.conversation_message_id]
        await bot.api.messages.delete(peer_id=m.peer_id, cmids=cmids, delete_for_all=True)
        log_action(m.peer_id, 0, m.from_id, "purge", str(n))
        await say(m, f"🧹 Удалено сообщений: {max(len(cmids) - 1, 0)}")
    except Exception:
        await say(m, "⚠️ Не вышло. Бот должен быть админом, а сообщения не старше 24 часов.")


@cmd("pin", "закреп", lvl=1)
async def c_pin(m, a, rest):
    if not m.reply_message:
        return await say(m, "Ответь командой на сообщение, которое нужно закрепить.")
    try:
        await bot.api.messages.pin(peer_id=m.peer_id,
                                   conversation_message_id=m.reply_message.conversation_message_id)
    except Exception:
        await say(m, "⚠️ Не вышло закрепить.")


@cmd("unpin", "открепить", lvl=1)
async def c_unpin(m, a, rest):
    try:
        await bot.api.messages.unpin(peer_id=m.peer_id)
    except Exception:
        await say(m, "⚠️ Не вышло открепить.")


# ================= НАСТРОЙКИ ФИЛЬТРОВ =================
async def toggle(m, a, key, title):
    if not a or a[0].lower() not in ("on", "off", "вкл", "выкл"):
        cur = "включено" if flag(m.peer_id, key) else "выключено"
        return await say(m, f"{title}: сейчас {cur}.\nИспользование: /{key} on|off")
    on = a[0].lower() in ("on", "вкл")
    set_set(m.peer_id, key, "1" if on else None)
    await say(m, ("✅ Включено: " if on else "❌ Выключено: ") + title)


@cmd("quiet", "тишина", lvl=2)
async def c_quiet(m, a, rest):
    await toggle(m, a, "quiet", "Режим тишины (пишут только хелперы и выше)")


@cmd("antilink", "антиссылки", lvl=2)
async def c_antilink(m, a, rest):
    await toggle(m, a, "antilink", "Анти-ссылки")


@cmd("antispam", "антиспам", lvl=2)
async def c_antispam(m, a, rest):
    await toggle(m, a, "antispam", "Антиспам")


@cmd("antimat", "антимат", lvl=2)
async def c_antimat(m, a, rest):
    await toggle(m, a, "antimat", "Антимат")


@cmd("slowmode", "слоумод", lvl=2)
async def c_slowmode(m, a, rest):
    if not a or not a[0].isdigit():
        return await say(m, "Использование: /slowmode секунды (0 — выключить)")
    n = min(int(a[0]), 600)
    set_set(m.peer_id, "slowmode", str(n) if n else None)
    await say(m, f"🐢 Slowmode: {n} сек." if n else "✅ Slowmode выключен.")


@cmd("addword", lvl=2)
async def c_addword(m, a, rest):
    if not a:
        return await say(m, "Использование: /addword слово")
    w = a[0].lower().replace("ё", "е")
    q("INSERT OR IGNORE INTO badwords(peer,word) VALUES(?,?)", (m.peer_id, w))
    await say(m, "✅ Слово добавлено.")
    await delete_msg(m.peer_id, m.conversation_message_id)


@cmd("delword", lvl=2)
async def c_delword(m, a, rest):
    if not a:
        return await say(m, "Использование: /delword слово")
    q("DELETE FROM badwords WHERE peer=? AND word=?", (m.peer_id, a[0].lower().replace("ё", "е")))
    await say(m, "✅ Слово удалено.")


@cmd("words", "стопслова", lvl=2)
async def c_words(m, a, rest):
    r = rows("SELECT word FROM badwords WHERE peer=? ORDER BY word", (m.peer_id,))
    await say(m, ("🤬 Стоп-слова: " + ", ".join(x[0] for x in r)) if r else "Список пуст.")
    await delete_msg(m.peer_id, m.conversation_message_id)


@cmd("kickdog", "собаки", lvl=2)
async def c_kickdog(m, a, rest):
    r = await chat_members(m.peer_id)
    if not r:
        return await say(m, "⚠️ Не могу получить участников. Бот должен быть админом беседы.")
    n = 0
    for p in (r.profiles or []):
        if getattr(p, "deactivated", None):
            if await kick(m.peer_id, p.id):
                n += 1
    await say(m, f"🐕 Исключено удалённых/заблокированных: {n}")


# ================= ПРИЗЫВ / ЖАЛОБЫ =================
@cmd("zov", "все", lvl=1)
async def c_zov(m, a, rest):
    ok = await tag_all(m, f"📢 {rest or 'Общий сбор!'}")
    if not ok:
        await say(m, "⚠️ Не могу получить участников. Бот должен быть админом беседы.")


@cmd("online", "онлайн", lvl=1)
async def c_online(m, a, rest):
    r = await chat_members(m.peer_id)
    if not r:
        return await say(m, "⚠️ Не могу получить участников. Бот должен быть админом беседы.")
    on = [p for p in (r.profiles or []) if int(getattr(p, "online", 0) or 0)]
    lines = [f"🟢 Онлайн: {len(on)} из {len(r.profiles or [])}"]
    lines += [f"• [id{p.id}|{p.first_name} {p.last_name}]" for p in on[:40]]
    await say(m, "\n".join(lines))


@cmd("adm", "админ", "модеры")
async def c_adm(m, a, rest):
    staff = staff_ids(m.peer_id)
    if not staff:
        return await say(m, "Руководство в беседе не назначено.")
    tags = "".join(f"[id{u}|{ZW}]" for u in staff)
    await m.answer(f"🆘 {await mention(m.from_id)} зовёт администрацию. {rest}\n{tags}")


@cmd("report", "репорт", "жалоба")
async def c_report(m, a, rest):
    staff = staff_ids(m.peer_id)
    if not staff:
        return await say(m, "Руководство в беседе не назначено.")
    lines = [f"🚨 Жалоба от {await mention(m.from_id)}"]
    if m.reply_message and m.reply_message.from_id > 0:
        lines.append(f"На: {await mention(m.reply_message.from_id)}")
        if m.reply_message.text:
            lines.append(f"Сообщение: {m.reply_message.text[:200]}")
    if rest:
        lines.append(f"Текст: {rest}")
    tags = "".join(f"[id{u}|{ZW}]" for u in staff)
    await m.answer("\n".join(lines) + "\n" + tags)


# ================= РАЗВЛЕЧЕНИЯ =================
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
       ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def safe_eval(node):
    if isinstance(node, ast.Expression):
        return safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        l, r = safe_eval(node.left), safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(r) > 100 or abs(l) > 1e6):
            raise ValueError("слишком большое число")
        return OPS[type(node.op)](l, r)
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](safe_eval(node.operand))
    raise ValueError("недопустимое выражение")


@cmd("calc", "calculator", "счёт")
async def c_calc(m, a, rest):
    if not rest:
        return await say(m, "Использование: /calc 2+2*2")
    try:
        expr = rest.replace("^", "**").replace(",", ".").replace("×", "*").replace("÷", "/")
        res = safe_eval(ast.parse(expr, mode="eval"))
        await say(m, f"🧮 {rest} = {round(res, 6) if isinstance(res, float) else res}")
    except ZeroDivisionError:
        await say(m, "🧮 Делить на ноль нельзя.")
    except Exception as e:
        await say(m, f"🧮 Ошибка: {e}")


@cmd("roll", "рандом")
async def c_roll(m, a, rest):
    n = int(a[0]) if a and a[0].isdigit() and int(a[0]) > 0 else 100
    await say(m, f"🎲 {await mention(m.from_id)} выбил: {random.randint(1, n)} (1–{n})")


@cmd("coin", "монетка")
async def c_coin(m, a, rest):
    await say(m, "🪙 " + random.choice(["Орёл", "Решка"]))


@cmd("choose", "выбери")
async def c_choose(m, a, rest):
    opts = [x.strip() for x in re.split(r"\||\bили\b", rest) if x.strip()]
    if len(opts) < 2:
        return await say(m, "Использование: /choose вариант 1 | вариант 2 | вариант 3")
    await say(m, f"🤔 Выбираю: {random.choice(opts)}")


@cmd("who", "кто")
async def c_who(m, a, rest):
    if not rest:
        return await say(m, "Использование: /who самый умный")
    r = await chat_members(m.peer_id)
    if not r:
        return await say(m, "⚠️ Не могу получить участников.")
    ids = [i.member_id for i in r.items if i.member_id and i.member_id > 0]
    if not ids:
        return
    u = random.choice(ids)
    await say(m, f"🎯 Кто {rest}? Это {await mention(u)}")


@cmd("rate", "оцени")
async def c_rate(m, a, rest):
    if not rest:
        return await say(m, "Использование: /rate что-нибудь")
    await say(m, f"⭐ «{rest}» — {random.randint(0, 10)}/10")


@cmd("ball", "шар")
async def c_ball(m, a, rest):
    if not rest:
        return await say(m, "Использование: /ball вопрос")
    await say(m, "🔮 " + random.choice([
        "Бесспорно", "Да", "Скорее да", "Знаки говорят — да", "Пока не ясно, спроси позже",
        "Лучше не рассказывать", "Даже не думай", "Мой ответ — нет", "Весьма сомнительно"]))


# ================= СОБЫТИЯ =================
LINK_RE = re.compile(
    r"(https?://|www\.|vk\.cc|vk\.com|t\.me|discord\.gg|\b[\w-]+\.(ru|com|net|org|me|gg|ly|su|xyz|io|tk|cc)\b)",
    re.IGNORECASE)
FLOOD = defaultdict(deque)
LAST_MSG = {}


def bad_word(peer, text):
    low = text.lower().replace("ё", "е")
    for (w,) in rows("SELECT word FROM badwords WHERE peer=?", (peer,)):
        if w and w in low:
            return w
    return None


@bot.on.chat_message(ChatActionRule(["chat_invite_user", "chat_invite_user_by_link"]))
async def on_join(m: Message):
    uid = m.action.member_id or m.from_id
    peer = m.peer_id
    if uid and uid < 0:
        return await say(m, f"👋 Я чат-менеджер {PROJECT}. Выдайте мне админку в беседе и пишите /help")
    if one("SELECT 1 FROM bans WHERE peer=? AND uid=?", (peer, uid)):
        await kick(peer, uid)
        return await say(m, f"🚫 {await mention(uid)} в банлисте — исключён.")
    w = get_set(peer, "welcome")
    if w == "off":
        return
    text = w or DEFAULT_WELCOME
    await say(m, text.replace("{name}", await mention(uid)).replace("{project}", PROJECT))


@bot.on.chat_message()
async def on_message(m: Message):
    peer, uid = m.peer_id, m.from_id
    if uid < 0:
        return
    lvl = level(peer, uid)
    now = time.time()
    text = (m.text or "").strip()
    text = re.sub(r"^\[club\d+\|[^\]]*\]\s*,?\s*", "", text)

    # --- возвращение из AFK ---
    r = one("SELECT ts FROM afk WHERE uid=?", (uid,))
    if r:
        q("DELETE FROM afk WHERE uid=?", (uid,))
        await say(m, f"👋 {await mention(uid)} вернулся (был AFK {fmt_dur(now - r[0])})")

    # --- кого-то из AFK упомянули ---
    tagged = {int(x) for x in re.findall(r"\[id(\d+)\|", m.text or "")}
    if m.reply_message and m.reply_message.from_id > 0:
        tagged.add(m.reply_message.from_id)
    for t in tagged:
        if t == uid:
            continue
        ar = one("SELECT reason,ts FROM afk WHERE uid=?", (t,))
        if ar:
            await say(m, f"💤 {await mention(t)} в AFK ({fmt_dur(now - ar[1])}): {ar[0]}")

    # --- мут ---
    mu = one("SELECT until FROM mutes WHERE peer=? AND uid=?", (peer, uid))
    if mu:
        if mu[0] > now:
            await delete_msg(peer, m.conversation_message_id)
            return
        q("DELETE FROM mutes WHERE peer=? AND uid=?", (peer, uid))

    # --- режим тишины ---
    if flag(peer, "quiet") and lvl < 1:
        await delete_msg(peer, m.conversation_message_id)
        return

    # --- фильтры (персонал освобождён) ---
    if lvl < 1:
        sm = get_set(peer, "slowmode")
        if sm and sm.isdigit():
            if now - LAST_MSG.get((peer, uid), 0) < int(sm):
                await delete_msg(peer, m.conversation_message_id)
                return
            LAST_MSG[(peer, uid)] = now

        if flag(peer, "antispam"):
            dq = FLOOD[(peer, uid)]
            dq.append(now)
            while dq and now - dq[0] > 6:
                dq.popleft()
            if len(dq) >= 6:
                dq.clear()
                await delete_msg(peer, m.conversation_message_id)
                q("INSERT OR REPLACE INTO mutes(peer,uid,until) VALUES(?,?,?)", (peer, uid, int(now) + 300))
                log_action(peer, uid, 0, "mute", "5 мин; флуд")
                await say(m, f"💥 {await mention(uid)} замучен на 5 мин. за флуд.")
                return

        if flag(peer, "antilink") and text and LINK_RE.search(text):
            await delete_msg(peer, m.conversation_message_id)
            await add_warn(m, uid, "Ссылка (антиссылки)", 0)
            return

        if flag(peer, "antimat") and text:
            w = bad_word(peer, text)
            if w:
                await delete_msg(peer, m.conversation_message_id)
                await add_warn(m, uid, "Стоп-слово (антимат)", 0)
                return

    # --- статистика ---
    q("INSERT INTO stats(peer,uid,cnt) VALUES(?,?,1) "
      "ON CONFLICT(peer,uid) DO UPDATE SET cnt=cnt+1", (peer, uid))

    # --- команды ---
    if not text or text[0] not in "/!":
        return
    parts = text[1:].split(maxsplit=1)
    if not parts:
        return
    name = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    fn = COMMANDS.get(name)
    if not fn:
        return
    try:
        await fn(m, rest.split(), rest)
    except Exception as e:
        await say(m, f"⚠️ Ошибка: {e}")


if __name__ == "__main__":
    bot.run_forever()
