#!/usr/bin/env python3
"""Скрейпер графіка відключень ДТЕК КРЕМ (dtek-krem.com.ua) для GitHub Actions.

Навіщо окремо від BlackoutBite: сайт ДТЕК за Imperva/Incapsula і блокує автоматичний
доступ ПО IP (перевірено багато разів з домашньої мережі/Pi — завжди заглушка). Але
раннери GitHub Actions Imperva не чіпає, тож звичайний headless-Playwright там
відкриває сторінку нормально, без жодного обходу челенджу (той самий підхід, що й у
mr-devboy/dtek-schedule, який так крутиться 6000+ разів). Цей скрипт запускається
НА раннері GitHub, а Pi лише читає опублікований schedule.json (public raw URL) —
див. providers/dtek_krem_bridge_http.py у BlackoutBite.

Дані на сторінці лежать вбудованим JS-обʼєктом `fact = {...}` (той самий прийом, що й
ng-state у alerts.energy). Беремо його, розбираємо на інтервали й пишемо компактний
schedule.json. Паралельно зберігаємо СИРИЙ fact (raw_fact.json) — щоб структуру й
семантику пів-годин можна було звірити з alerts.energy та за потреби підправити
мапінг нижче (див. _STATE напис).

Запуск локально (для розробки — з мережі, де ДТЕК не блокує):
    pip install -r requirements.txt && python -m playwright install chromium
    python scraper.py --region kr --groups 1.1,1.2,2.1,2.2,... --out schedule.json
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

KYIV_TZ = ZoneInfo("Europe/Kyiv")

# {region: URL}. Поки лише Київська обл. (kr) — єдина, що потрібна BlackoutBite.
REGION_URLS = {
    "kr": "https://www.dtek-krem.com.ua/ua/shutdowns",
}

# `... fact = { ... }` — як у mr-devboy (SHUTDOWNS_DATA_MATCHER). Межі обʼєкта
# знаходимо балансуванням дужок (надійніше за жадібний regex до останньої `}`).
_FACT_RE = re.compile(r"\bfact\s*=\s*\{")

# Стан години -> (чи є відключення, зміщення початку хв, зміщення кінця хв від :00).
# ПРИПУЩЕННЯ (за назвами станів ДТЕК; звіряємо з alerts.energy на 1-му запуску):
#   "yes"    = світло є весь час  -> без відключення
#   "no"     = світла нема весь час
#   "first"  = нема в ПЕРШІ 30 хв (HH:00–HH:30)
#   "second" = нема в ДРУГІ 30 хв (HH:30–HH+1:00)
_STATE = {
    "no": (0, 60),
    "first": (0, 30),
    "second": (30, 60),
}


def _looks_blocked(html: str) -> bool:
    low = html.lower()
    return "_incapsula_resource" in low or "incapsula" in low or "request unsuccessful" in low


def scrape_fact(region: str, attempts: int = 3, timeout_ms: int = 60_000) -> dict:
    """fact із кількома спробами. Дані вбудовані у HTML, тож networkidle не
    обовʼязковий (на сторінці ДТЕК бувають довгі запити/реклама, що не дають йому
    настати) — чекаємо його мʼяко, далі коротка пауза на можливий JS-челендж. Якщо
    прийшла заглушка Imperva — перезавантажуємо. Фінальний збій — із діагностикою в
    лог Actions (title/довжина/incapsula), щоб було ясно, що саме не так."""
    url = REGION_URLS[region]
    last_err = "невідомо"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            for attempt in range(1, attempts + 1):
                try:
                    page.goto(url, wait_until="load", timeout=timeout_ms)
                    try:
                        page.wait_for_load_state("networkidle", timeout=15_000)
                    except PlaywrightTimeoutError:
                        pass
                    page.wait_for_timeout(3_000)
                    html = page.content()
                    if _looks_blocked(html):
                        last_err = "сторінка схожа на заглушку Imperva/Incapsula"
                        print(f"[спроба {attempt}/{attempts}] {last_err} — перезавантажую…")
                        page.wait_for_timeout(5_000)
                        continue
                    return extract_fact(html)
                except (PlaywrightTimeoutError, ValueError) as e:
                    last_err = f"{type(e).__name__}: {e}"
                    print(f"[спроба {attempt}/{attempts}] не вдалось — {last_err}")
                    page.wait_for_timeout(5_000)
            try:
                html = page.content()
                diag = f"title={page.title()!r}, html_len={len(html)}, incapsula={_looks_blocked(html)}"
            except Exception:
                diag = "сторінку не вдалося прочитати"
            raise RuntimeError(f"не отримав fact за {attempts} спроб ({last_err}); {diag}")
        finally:
            browser.close()


def extract_fact(html: str) -> dict:
    """Витягти обʼєкт `fact = {...}` балансуванням фігурних дужок (з урахуванням
    рядків/екранування), щоб не залежати від того, що йде після нього на сторінці."""
    m = _FACT_RE.search(html)
    if m is None:
        raise ValueError("на сторінці немає `fact = {` (змінився формат або прийшла заглушка Imperva)")
    start = m.end() - 1  # позиція першої '{'
    depth, in_str, esc = 0, False, False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start : i + 1])
    raise ValueError("незбалансовані дужки в `fact` — обʼєкт не закрито")


def _day_dict(fact: dict, day_key_candidates: list[str]) -> dict | None:
    """fact орієнтований day-first (data[день][група][година]) — повертає піддерево
    на потрібний день за першим ключем, що підійшов (дата або 'today'/'tomorrow')."""
    for key in day_key_candidates:
        if key in fact and isinstance(fact[key], dict):
            return fact[key]
    return None


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Склеїти суміжні (кінець == початок наступного)."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if merged and merged[-1][1] == start:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def parse_group_day(day_dict: dict | None, group: str) -> list[str] | None:
    """Список інтервалів "HH:MM-HH:MM" для черги на один день. None — день не
    опубліковано (нема піддерева/черги). [] — опубліковано, відключень нема."""
    if day_dict is None:
        return None
    hours = day_dict.get(group)
    if hours is None:
        return None
    raw: list[tuple[float, float]] = []
    for hour in range(24):
        # ДТЕК кодує години ключами "1".."24" (зі зміщенням +1), значення — стан.
        state = hours.get(str(hour + 1)) if isinstance(hours, dict) else None
        info = _STATE.get(str(state).lower()) if state is not None else None
        if info is None:
            continue
        start_min, end_min = info
        raw.append((hour + start_min / 60, hour + end_min / 60))
    return [f"{_fmt(s)}-{_fmt(e)}" for s, e in _merge(raw)]


def _fmt(hour: float) -> str:
    h = int(hour)
    m = int(round((hour - h) * 60))
    return f"{h:02d}:{m:02d}"


def build_schedule(fact: dict, region: str, groups: list[str], now: datetime) -> dict:
    today = now.date()
    tomorrow = today + timedelta(days=1)
    today_dict = _day_dict(fact, [today.isoformat(), "today"])
    tomorrow_dict = _day_dict(fact, [tomorrow.isoformat(), "tomorrow"])
    return {
        "version": 1,
        "updated_at": now.isoformat(),
        "source": "dtek-krem.com.ua",
        "region": region,
        "today_date": today.isoformat(),
        "tomorrow_date": tomorrow.isoformat(),
        "groups": {
            g: {
                "today": parse_group_day(today_dict, g),
                "tomorrow": parse_group_day(tomorrow_dict, g),
            }
            for g in groups
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="kr", choices=sorted(REGION_URLS))
    ap.add_argument("--groups", default="1.1,1.2,2.1,2.2,3.1,3.2,4.1,4.2,5.1,5.2,6.1,6.2")
    ap.add_argument("--out", default="schedule.json")
    ap.add_argument("--raw-out", default="raw_fact.json", help="сирий fact — для звірки структури")
    args = ap.parse_args()

    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    fact = scrape_fact(args.region)

    with open(args.raw_out, "w", encoding="utf-8") as f:
        json.dump(fact, f, ensure_ascii=False, indent=2)

    schedule = build_schedule(fact, args.region, groups, datetime.now(KYIV_TZ))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)

    # Коротка діагностика в лог Actions — одразу видно, чи розпарсилось.
    print(f"OK: {args.out} — top-level fact keys: {sorted(fact.keys())[:6]}")
    for g in groups:
        gd = schedule["groups"][g]
        print(f"  {g}: today={gd['today']} tomorrow={gd['tomorrow']}")


if __name__ == "__main__":
    main()
