import datetime as dt
import hashlib
import re

import calendar_service as calendar
import organizer
import workspace_store

KEY = "day-brief-settings"


def settings(value=None):
    store = workspace_store.store()
    if value is not None:
        if any(x and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", x) for x in value.values()):
            raise ValueError("Укажи время в формате ЧЧ:ММ")
        store.cache(KEY, value)
    return (store.cache(KEY) or {}).get("data", {"morning":"","evening":""})


def build(day):
    store = workspace_store.store()
    events = calendar.day_plan(day)
    tasks = organizer.store().execute({"operation":"list","category":"task"}, "")["entries"]
    letters = (store.cache("dashboard:yandex:inbox") or {}).get("data", [])
    conflicts = []
    timed = [event for event in events if event.get("start")]
    for index, event in enumerate(timed):
        for other in timed[index+1:]:
            if other["start"] >= event["end"]:
                break
            conflicts.append(f'{event["title"]} / {other["title"]}')
    return {"events":events,"tasks":[task["title"] for task in tasks[:5]],
            "mail":[item["summary"] for item in sorted(
                (item for item in letters if (item.get("importance") or 0)>=5),
                key=lambda item:item["importance"],reverse=True)[:3]],"conflicts":conflicts}


def deliver(now=None):
    now = now or dt.datetime.now(calendar.ZONE)
    store = workspace_store.store()
    for slot, at in settings().items():
        if not at or now.strftime("%H:%M") < at:
            continue
        ident = hashlib.sha256(f"day-brief|{now.date()}|{slot}".encode()).hexdigest()[:32]
        with store.db() as db:
            if db.execute("SELECT 1 FROM inbox WHERE id=?", (ident,)).fetchone():
                continue
        day = now.date() + dt.timedelta(days=int(slot=="evening"))
        data = build(day.isoformat())
        lines = [f'{event["start"]} {event["title"]}'.strip() for event in data["events"]]
        lines += ["Задачи: "+", ".join(data["tasks"])] if data["tasks"] else []
        lines += ["Письма: "+" • ".join(data["mail"])] if data["mail"] else []
        lines += ["Пересечения: "+"; ".join(data["conflicts"])] if data["conflicts"] else []
        with store.db() as db:
            db.execute("INSERT OR IGNORE INTO inbox VALUES(?,?,?,?,0)",
                       (ident,"План на сегодня" if slot=="morning" else "План на завтра",
                        "\n".join(lines)[:6000] or "Запланированных дел нет.",now.timestamp()))
