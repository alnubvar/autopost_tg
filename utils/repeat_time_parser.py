# utils/repeat_time_parser.py

import re


def normalize_text(text: str) -> str:
    return (
        text.lower()
        .replace(",", " ")
        .replace(":", " ")
        .strip()
    )


def parse_interval(text: str) -> int | None:
    hours = 0
    minutes = 0

    h_match = re.search(r"(\d+)\s*h", text)
    m_match = re.search(r"(\d+)\s*m", text)

    if h_match:
        hours = int(h_match.group(1))
    if m_match:
        minutes = int(m_match.group(1))

    total = hours * 60 + minutes

    if total == 0:
        return None

    if total < 15:
        raise ValueError("Минимальный интервал — 15 минут")

    return total


def parse_times(text: str) -> list[str]:
    parts = text.split()
    times = []
    buf = []

    for p in parts:
        if not p.isdigit():
            continue

        if len(p) == 4:
            h, m = p[:2], p[2:]
            buf = []
        else:
            buf.append(p)
            if len(buf) < 2:
                continue
            h, m = buf
            buf = []

        hour = int(h)
        minute = int(m)

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Некорректное время")

        times.append(f"{hour:02d}:{minute:02d}")

    if not times:
        raise ValueError("Время не распознано")

    return sorted(set(times))


def parse_repeat_time(text: str) -> dict:
    normalized = normalize_text(text)

    interval = parse_interval(normalized)
    if interval:
        return {
            "type": "interval",
            "step_minutes": interval,
        }

    return {
        "type": "fixed",
        "times": parse_times(normalized),
    }
