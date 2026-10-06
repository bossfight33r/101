"""Расписание: длинное видео в long_time (локальное время канала), шортсы после него с интервалом.
Дневные лимиты канала считаются по локальной дате. Время — aware, наружу отдаём UTC."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from techstudio.schemas import Channel, Publication

LEAD = timedelta(minutes=30)  # не планируем ближе, чем через 30 минут
MAX_DAYS = 366


class ScheduleError(RuntimeError):
    pass


def _counts(pubs: list[Publication], tz: ZoneInfo) -> tuple[Counter, Counter]:
    longs, shorts = Counter(), Counter()
    for p in pubs:
        if p.status == "failed":
            continue
        d = p.scheduled_at.astimezone(tz).date()
        (longs if p.kind == "long" else shorts)[d] += 1
    return longs, shorts


def _at(d: date, hhmm: str, tz: ZoneInfo) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(d, time(h, m), tzinfo=tz)


def plan(
    channel: Channel, existing: list[Publication], now: datetime, n_shorts: int
) -> tuple[datetime, list[datetime]]:
    lim = channel.daily_limits
    if lim.long < 1:
        raise ScheduleError("daily_limits.long = 0: длинные видео не публикуются")
    if n_shorts and lim.shorts < 1:
        raise ScheduleError("daily_limits.shorts = 0: шортсы не публикуются")
    tz = ZoneInfo(channel.schedule.timezone)
    longs, shorts = _counts(existing, tz)
    earliest = now.astimezone(UTC) + LEAD

    d = earliest.astimezone(tz).date()
    for _ in range(MAX_DAYS):
        cand = _at(d, channel.schedule.long_time, tz)
        if cand.astimezone(UTC) >= earliest and longs[d] < lim.long:
            break
        d += timedelta(days=1)
    else:
        raise ScheduleError("нет свободного дня для длинного видео")
    long_at = cand.astimezone(UTC)

    step = timedelta(hours=channel.schedule.shorts_interval_hours)
    out: list[datetime] = []
    t = long_at + step
    for _ in range(n_shorts):
        for _ in range(MAX_DAYS * 24):
            local_day = t.astimezone(tz).date()
            if shorts[local_day] < lim.shorts:
                break
            # день заполнен — первый слот следующего дня: long_time + интервал
            t = (_at(local_day + timedelta(days=1), channel.schedule.long_time, tz)).astimezone(
                UTC
            ) + step
        else:
            raise ScheduleError("нет свободного слота для шортса")
        out.append(t)
        shorts[t.astimezone(tz).date()] += 1
        t = t + step
    return long_at, out
