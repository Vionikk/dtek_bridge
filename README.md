# dtek_bridge — DTEK KREM schedule scraper (GitHub Actions)

Окремий **самостійний** проєкт (не частина BlackoutBite, лише лежить поруч у теці).
Скрейпить графік відключень ДТЕК КРЕМ з `dtek-krem.com.ua` і публікує готовий
`schedule.json` у гілку `data` — щоб Blackout Bite на Raspberry Pi читав його звідти.

## Навіщо він узагалі

Сайт ДТЕК за Imperva/Incapsula і блокує автоматичний доступ **по IP** — з домашньої
мережі / Pi завжди повертається заглушка-челендж, хоч httpx, хоч Playwright. Але IP
раннерів GitHub Actions Imperva **не** блокує, тож там звичайний headless-Playwright
відкриває сторінку як нормальний відвідувач (без жодного обходу захисту). Тому
скрейпинг крутиться тут, на Actions, а Pi лише читає результат звичайним GET з
`raw.githubusercontent.com`.

Дані на сторінці — вбудований JS-обʼєкт `fact = {...}`; `scraper.py` дістає його,
розбирає в інтервали і пише компактний `schedule.json`.

## Налаштування (одноразово)

1. Створи **публічний** репозиторій на GitHub (напр. `dtek-schedule-bridge`) і поклади
   в нього вміст цієї теки (`scraper.py`, `requirements.txt`, `.github/`, цей README).
   Публічний — щоб хвилини Actions були безлімітні, а Pi читав без токена. Графік
   відключень не є чутливими даними.

   ```bash
   cd dtek_bridge
   git init -b main
   git add .
   git commit -m "init dtek scraper"
   git remote add origin git@github.com:<ти>/dtek-schedule-bridge.git
   git push -u origin main
   ```

2. У репо на GitHub: **Settings → Actions → General → Workflow permissions** →
   увімкни **Read and write permissions** (інакше Action не запушить гілку `data`).

3. Запусти вручну: вкладка **Actions → Scrape DTEK schedule → Run workflow**.
   Далі він ітиме сам за розкладом (`cron: "*/15 * * * *"`).

   ⚠️ **GitHub-cron — best-effort.** Заплановані запуски Actions сильно затримуються
   й пропускаються, особливо часті інтервали: `*/15` на практиці рідко витримується,
   реально виходить раз на 30–60+ хв. Збільшити частоту в cron це не лікує (GitHub
   усе одно throttle-ить). Тому BlackoutBite бере це до уваги: `max_age_minutes: 180`
   дає великий запас, щоб нерегулярність не спричиняла хибних «джерело недоступне», а
   рекомендоване основне джерело бота — не цей місток, а `alerts_energy_site` (пряме,
   без залежності від GitHub). Місток — запасне/для звірки.

4. Після першого успішного запуску файл буде тут:
   `https://raw.githubusercontent.com/<ти>/dtek-schedule-bridge/data/schedule.json`
   Цю адресу встав у BlackoutBite `config.yaml`:

   ```yaml
   provider: dtek_krem_bridge
   dtek_bridge:
     url: "https://raw.githubusercontent.com/<ти>/dtek-schedule-bridge/data/schedule.json"
     # max_age_minutes: 180   # старіший графік -> джерело вважається недоступним
   ```

## Структура `fact` (підтверджено наживо 2026-10-27)

```jsonc
fact = {
  "data": {
    "1793052000": {                 // ключ дня — Unix-timestamp (00:00 Kyiv)
      "GPV2.2": {"1":"yes", ... "9":"second","10":"no", ... "24":"yes"}
    }
  },
  "today":  1793052000,             // timestamp сьогоднішнього дня
  "update": "27.10.2026 09:51"
}
```
- День — по timestamp у `data` (не дата-рядок); `_data_by_date()` розкодовує його в
  київську дату. Завтра зʼявляється окремим timestamp, коли ДТЕК публікує.
- Черга — з префіксом `GPV` (`GPV2.2`), години — ключі `"1".."24"` (зі зміщенням +1,
  тобто `"9"` = 08:00–09:00).
- Стани: `yes` = світло весь час, `no` = нема всю годину, `first` = нема перші 30 хв,
  `second` = нема другі 30 хв. **Мапінг звірено з alerts.energy** на чергах 1.1/2.2/3.1/6.2
  — збіг точний, включно з `20:00–24:00`.

`raw_fact.json` публікується поряд із `schedule.json` — лишається для майбутніх звірок,
якщо ДТЕК змінить формат.

## Локальний запуск (лише з мережі, де ДТЕК не блокує)

```bash
pip install -r requirements.txt
python -m playwright install chromium
python scraper.py --region kr --out schedule.json
```
