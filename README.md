# SERP Monitor
Автоматичний аналіз SERP для 350+ ключових слів. Запускається щопонеділка, без жодної ручної роботи.
Автор — [Назар Носаненко](https://www.linkedin.com/in/nazar-nosanenko-308639163/), SEO Team Lead у Stripo.email.

## Що робить

- Збирає топ-10 результатів Google для кожного ключового слова через SerpAPI
- Класифікує кожен URL: YouTube / Reddit / Social / Own / Article
- Відправляє патерн до Claude (Anthropic API) → отримує стратегічну рекомендацію по кожному кластеру
- Щотижня записує все в новий таб Google Sheets

## Стек

| Інструмент | Роль |
|------|------|
| SerpAPI | Дані з SERP |
| Anthropic API (Claude Haiku) | Аналіз кластерів |
| GitHub Actions | Щотижневий запуск |
| Google Sheets | Результати |

**Вартість інфраструктури: $0**

## Налаштування

### 1. Клонуй репо
```bash
git clone https://github.com/YOUR_USERNAME/serp-monitor.git
```

### 2. Підготуй keywords.csv
Два стовпці: `keyword` і `cluster`
```
keyword,cluster
email template builder,Email Builders
drag and drop email editor,Email Builders
```

### 3. Налаштуй Google Sheets
- Створи новий Google Sheet
- Створи Service Account у Google Cloud Console
- Поділися таблицею з email Service Account (роль — Редактор)
- Завантаж JSON Service Account

### 4. Додай GitHub Secrets
Перейди в **Settings → Secrets → Actions** і додай:

| Secret | Значення |
|--------|-------|
| `SERPAPI_KEY` | Твій ключ SerpAPI |
| `ANTHROPIC_KEY` | Твій ключ Anthropic API |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Повний вміст JSON Service Account |
| `GOOGLE_SHEET_ID` | ID таблиці з URL Google Sheet |
| `YOUR_DOMAIN` | Твій домен, наприклад `example.com` |

### 5. Налаштуй автоматичний запуск

Створи файл `.github/workflows/serp.yml` у репо з таким вмістом:

```yaml
name: Weekly SERP Analysis

on:
  schedule:
    - cron: '0 7 * * 1'  # щопонеділка о 07:00 UTC
  workflow_dispatch:       # також можна запустити вручну

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install requests cryptography

      - name: Run SERP Analyzer
        env:
          SERPAPI_KEY: ${{ secrets.SERPAPI_KEY }}
          ANTHROPIC_KEY: ${{ secrets.ANTHROPIC_KEY }}
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
          GOOGLE_SHEET_ID: ${{ secrets.GOOGLE_SHEET_ID }}
          YOUR_DOMAIN: ${{ secrets.YOUR_DOMAIN }}
        run: python serp_analyzer.py
```

Після цього: **Actions → Weekly SERP Analysis → Run workflow** — перший запуск вручну, далі автоматично щопонеділка.

## Результат

Щотижня створюється новий таб `SERP-2026-W21` з:
- Усіма топ-10 URL по кожному ключу з класифікацією типу
- AI-рекомендацією по кожному кластеру від Claude

## Ліцензія
MIT
