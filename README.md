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
   Далі він ітиме сам щогодини (`cron: "7 * * * *"`; для 30-хв свіжості постав
   `*/30 * * * *` — на публічному репо це безкоштовно).

4. Після першого успішного запуску файл буде тут:
   `https://raw.githubusercontent.com/<ти>/dtek-schedule-bridge/data/schedule.json`
   Цю адресу встав у BlackoutBite `config.yaml`:

   ```yaml
   provider: dtek_krem_bridge
   dtek_bridge:
     url: "https://raw.githubusercontent.com/<ти>/dtek-schedule-bridge/data/schedule.json"
     # max_age_minutes: 180   # старіший графік -> джерело вважається недоступним
   ```

## ⚠️ Перша звірка (важливо)

Структуру `fact` і семантику пів-годин (стани `first`/`second`) **не перевірено з
незаблокованого середовища** — мапінг у `scraper.py` (`_STATE`) зроблено за назвами
станів ДТЕК і логікою mr-devboy/dtek-schedule, але його треба підтвердити:

- Action публікує поряд `raw_fact.json` — **сирий** `fact`. Після першого запуску
  відкрий його і `schedule.json`, і звір графік своєї черги з тим, що показує
  alerts.energy на той самий день.
- Якщо збігається — усе гаразд. Якщо пів-години переплутані (напр. "перші 30 хв"
  насправді "другі") — поправ відповідність у `_STATE` (`"first"`/`"second"`) і
  перезапусти.

Якщо `raw_fact.json` виявиться іншої форми (не `data[день][черга][година]`), надішли
його структуру — підженемо `parse_group_day()`/`_day_dict()` під неї.

## Локальний запуск (лише з мережі, де ДТЕК не блокує)

```bash
pip install -r requirements.txt
python -m playwright install chromium
python scraper.py --region kr --out schedule.json
```
