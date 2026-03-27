import calendar
from datetime import date, datetime, time, timedelta

import pytz

from config import DEFAULT_TIMEZONE


def get_timezone(timezone_name: str | None = None):
    return pytz.timezone(timezone_name or DEFAULT_TIMEZONE)


def ensure_timezone(dt: datetime, timezone_name: str | None = None) -> datetime:
    tz = get_timezone(timezone_name)
    if dt.tzinfo is None:
        return tz.localize(dt)
    return dt.astimezone(tz)


def build_recurrence_config(
    date_selection: dict,
    time_selection: dict,
    timezone_name: str | None = None,
) -> dict:
    return {
        "timezone": timezone_name or DEFAULT_TIMEZONE,
        "date_selection": date_selection,
        "time_selection": time_selection,
    }


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _fixed_day_occurrences(
    tz,
    current_date: date,
    time_selection: dict,
) -> list[datetime]:
    out = []
    for value in sorted(set(time_selection["times"])):
        hour, minute = map(int, value.split(":"))
        out.append(tz.localize(datetime.combine(current_date, time(hour, minute))))
    return out


def _interval_day_occurrences(
    tz,
    current_date: date,
    time_selection: dict,
) -> list[datetime]:
    step = timedelta(minutes=time_selection["step_minutes"])
    current = tz.localize(datetime.combine(current_date, time(0, 0)))
    end = tz.localize(datetime.combine(current_date, time(23, 59)))
    out = []

    while current <= end:
        out.append(current)
        current += step

    return out


def _day_occurrences(
    tz,
    current_date: date,
    time_selection: dict,
) -> list[datetime]:
    if time_selection["type"] == "fixed":
        return _fixed_day_occurrences(tz, current_date, time_selection)
    return _interval_day_occurrences(tz, current_date, time_selection)


def _filter_after(occurrences: list[datetime], start_after: datetime | None) -> list[datetime]:
    if start_after is None:
        return occurrences
    return [item for item in occurrences if item > start_after]


def iter_occurrences(
    config: dict,
    start_after: datetime | None = None,
    limit: int | None = None,
) -> list[datetime]:
    tz = get_timezone(config.get("timezone"))
    if start_after is not None:
        start_after = ensure_timezone(start_after, config.get("timezone"))

    date_selection = config["date_selection"]
    time_selection = config["time_selection"]
    mode = date_selection["mode"]

    if mode == "dates":
        dates = sorted({_parse_date(item) for item in date_selection.get("dates", [])})
        out: list[datetime] = []

        for current_date in dates:
            out.extend(_filter_after(_day_occurrences(tz, current_date, time_selection), start_after))
            if limit and len(out) >= limit:
                return out[:limit]

        return out[:limit] if limit else out

    out: list[datetime] = []
    start_date = _parse_date(date_selection.get("start_date") or datetime.now(tz).date().isoformat())
    current_date = start_date

    if start_after is not None and start_after.date() > current_date:
        current_date = start_after.date()

    weekdays = set(date_selection.get("weekdays", []))
    month_days = set(date_selection.get("days", []))
    safety_days = 366 * 5

    for _ in range(safety_days):
        matched = False
        if mode == "weekdays" and current_date.weekday() in weekdays:
            matched = True
        elif mode == "month_days":
            _, max_day = calendar.monthrange(current_date.year, current_date.month)
            matched = current_date.day in month_days and current_date.day <= max_day

        if matched:
            out.extend(_filter_after(_day_occurrences(tz, current_date, time_selection), start_after))
            if limit and len(out) >= limit:
                return out[:limit]

        current_date += timedelta(days=1)

    return out[:limit] if limit else out


def get_first_occurrence(config: dict, now: datetime | None = None) -> datetime | None:
    occurrences = iter_occurrences(config, start_after=now, limit=1)
    return occurrences[0] if occurrences else None


def get_next_occurrence(config: dict, after_dt: datetime) -> datetime | None:
    occurrences = iter_occurrences(config, start_after=after_dt, limit=1)
    return occurrences[0] if occurrences else None


def get_end_at(config: dict) -> datetime | None:
    if config["date_selection"]["mode"] != "dates":
        return None

    occurrences = iter_occurrences(config)
    if not occurrences:
        return None
    return occurrences[-1]


def get_total_publications(config: dict, now: datetime | None = None) -> int | None:
    if config["date_selection"]["mode"] != "dates":
        return None
    return len(iter_occurrences(config, start_after=now))


def summarize_recurrence(config: dict, now: datetime | None = None) -> dict:
    first_run = get_first_occurrence(config, now=now)
    end_at = get_end_at(config)
    total = get_total_publications(config, now=now)
    return {
        "first_run_at": first_run,
        "end_at": end_at,
        "total_publications": total,
    }


def describe_recurrence(config: dict) -> str:
    date_selection = config["date_selection"]
    time_selection = config["time_selection"]

    if date_selection["mode"] == "dates":
        date_label = f"даты: {len(date_selection.get('dates', []))}"
    elif date_selection["mode"] == "weekdays":
        names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        date_label = "дни недели: " + ", ".join(
            names[index] for index in sorted(date_selection.get("weekdays", []))
        )
    else:
        date_label = "дни месяца: " + ", ".join(
            str(day) for day in sorted(date_selection.get("days", []))
        )

    if time_selection["type"] == "fixed":
        time_label = ", ".join(time_selection["times"])
    else:
        time_label = f"каждые {time_selection['step_minutes']} мин"

    return f"{date_label}; {time_label}"
