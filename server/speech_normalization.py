"""Render written numbers as speech before passing text to XTTS."""
import datetime
import re
from num2words import num2words

RU_MONTHS = "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()
EN_MONTHS = "January February March April May June July August September October November December".split()


def normalize(text, lang):
    if lang not in ("ru", "en"):
        return text

    def number(value, **options):
        return num2words(int(value), lang=lang, **options)

    def date(match):
        day, month, year = map(int, match.groups())
        try:
            datetime.date(year, month, day)
        except ValueError:
            return match.group()
        ordinal = number(day, to="ordinal")
        if lang == "en":
            return f"{ordinal} of {EN_MONTHS[month-1]} {number(year, to='year')}"
        ordinal = re.sub(r"(ый|ой|ий)$", lambda m: "ье" if ordinal.endswith("третий") else "ое", ordinal)
        return f"{ordinal} {RU_MONTHS[month-1]} {number(year, to='ordinal', case='g')} года"

    def clock(match):
        hour, minute = map(int, match.groups())
        if hour > 23 or minute > 59:
            return match.group()
        if lang == "en":
            return f"{number(hour)} {('oh ' if minute < 10 else '') + number(minute) if minute else 'hundred'}"
        return f"{number(hour)} {'ноль ' if 0 < minute < 10 else ''}{number(minute)}" if minute else f"{number(hour)} ровно"

    def quantity(match):
        raw, unit = match.groups()
        negative = raw.startswith(("-", "−"))
        raw = raw.lstrip("-−").replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
        parts = re.split(r"[.,]", raw)
        whole = number(parts[0])
        if len(parts) == 2:
            fraction = parts[1]
            if lang == "ru" and len(fraction) <= 3:
                whole = number(parts[0], gender="f")
                whole += " целая " if int(parts[0]) % 10 == 1 and int(parts[0]) % 100 != 11 else " целых "
                whole += number(fraction, gender="f")
                singular = int(fraction) % 10 == 1 and int(fraction) % 100 != 11
                whole += " " + (("десятая","сотая","тысячная") if singular else ("десятых","сотых","тысячных"))[len(fraction)-1]
            else:
                whole += (" запятая " if lang=="ru" else " point ") + " ".join(number(digit) for digit in fraction)
        if negative:
            whole = ("минус " if lang=="ru" else "minus ") + whole
        if unit == "%":
            n = int(parts[0])
            suffix = "percent"
            if lang == "ru":
                suffix = ("процента" if len(parts)==2 else "процентов" if 11<=n%100<=14
                          else "процент" if n%10==1 else "процента" if 2<=n%10<=4 else "процентов")
            whole += " " + suffix
        return whole

    text = re.sub(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)", date, text)
    text = re.sub(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", clock, text)
    return re.sub(r"(?<!\w)([-−]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d{1,18})(?:[.,]\d{1,8})?)(?:\s*(%))?(?!\w)", quantity, text)
