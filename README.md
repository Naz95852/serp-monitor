# SERP Monitor
Автоматичний аналіз SERP для ключових слів. Запускається щопонеділка, без жодної ручної роботи.
Автор — [Назар Носаненко](https://www.linkedin.com/in/nazar-nosanenko-308639163/)), SEO Team Lead у Stripo.email.

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

### 5. Запуск
Автоматично щопонеділка о 07:00 UTC.
Або вручну: **Actions → Weekly SERP Analysis → Run workflow**

## Результат

Щотижня створюється новий таб `SERP-2026-W21` з:
- Усіма топ-10 URL по кожному ключу з класифікацією типу
- AI-рекомендацією по кожному кластеру від Claude

## Ліцензія
MIT
