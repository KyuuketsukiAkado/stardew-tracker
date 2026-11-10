# Аудит и AQA репозитория Stardew Tracker

Дата: 2026-11-08. Объект: `KyuuketsukiAkado/stardew-tracker`, ветка `arena/3a3ecc90-stardew-tracker`
(база — `ef22c6d`). Отчёт описывает состояние **до** и **после** рефакторинга, чтобы изменения
можно было проверить независимо.

## 1. Резюме

Проект — локальный трекер сохранений Stardew Valley на чистой стандартной библиотеке Python:
XML-парсер, сборка состояния, живой HTTP-дашборд и автономный HTML-отчёт. Функционально он
рабочий (45 тестов проходили), но страдал от типичных проблем выросшего прототипа:

- весь код — один файл `tracker.py` на 2114 строк: константы, XML, парсер, бизнес-логика,
  рендер, HTTP-сервер и CLI;
- кэши без блокировок и с утечкой изменяемых структур между запросами;
- поток наблюдателя мог молча умереть на `SaveError` (он наследуется от `SystemExit`);
- сервер по умолчанию слушал `0.0.0.0`, отдавая локальные сейвы всей сети;
- XML разбирался без защиты от `DOCTYPE`/`ENTITY` (billion laughs);
- в мультиплеере фермеры из `farmhands` могли не находиться из-за лимита обхода в 4000 узлов;
- формула Farmer Level включала удачу, завышая перфекцию;
- не было гейтов по линтерам, типам, безопасности и покрытию.

После рефакторинга: 20 модулей пакета `stardew_tracker`, тонкая совместимая обёртка
`tracker.py`, 129 тестов, 90% покрытия, 0 замечаний ruff/bandit, чистый mypy с проверкой тел
неаннотированных функций, CI с матрицей Python 3.9/3.11/3.13 и отдельным quality-job.

Поведение проверено побайтово: состояние и автономный HTML для синтетического сейва совпадают
с версией `ef22c6d` с точностью до поля `generated` (время сборки).

## 2. Методика

1. Чтение кода и документации (`README.md`, `TZ.md`, `CHANGELOG.md`), ручная трассировка
   основных сценариев: поиск сейва → разбор XML → состояние → HTML → HTTP API.
2. Запуск имеющегося набора тестов и фиксация baseline-состояния/HTML.
3. Статический анализ: `ruff`, `mypy --check-untyped-defs`, `bandit`, `py_compile`.
4. Измерение покрытия `coverage.py` до и после.
5. Проверка фронтенда: извлечение inline-JS и `node --check`, поиск XSS-векторов
   (`innerHTML`, интерполяции без `esc()`), inline-обработчиков и внешних зависимостей.
6. Ручные проверки безопасности: XML-бомбы, path traversal, CORS, заголовки, лимиты POST.
7. Рефакторинг с сохранением публичного CLI/API и последующей дифференциальной проверкой
   выходных данных.

## 3. Метрики

| Метрика | До | После |
|---|---:|---:|
| Тесты (`unittest`) | 45 | **129** |
| Покрытие `tracker.py` / пакета | 68% | **90%** |
| Максимальный размер файла Python | 2114 строк | **459** (`saveparser.py`)* |
| Ruff (default) | 1 замечание | **0** |
| Bandit | 4 замечания (3 Medium) | **0** |
| mypy | «успех» без проверки тел функций | **0** с `check_untyped_defs` |
| CI-гейты | тесты + smoke + необязательный flake8 | **тесты, ruff, format, mypy, bandit, coverage ≥85%** |
| Матрица Python | 3.9 / 3.11 / 3.13 | 3.9 / 3.11 / 3.13 |
| JS-проверка | нет | `node --check` + запрет inline-обработчиков |
| Совместимость Python | не проверялась | `vermin -t=3.9-` в CI (фактически код совместим с 3.8+) |

\* `build_data.py` (1344 строки) — отдельный офлайн-сборщик данных; он вынесен из mypy через
override и покрыт тестами на PNG-кодек и вспомогательные функции, но пока не разбит на модули.

## 4. Находки

Приоритеты: **High** — ошибка/риск, влияющие на корректность или безопасность; **Medium** —
устойчивость, производительность, сопровождаемость; **Low** — гигиена.

| ID | Приоритет | Область | Находка | Исправление |
|---|---|---|---|---|
| SEC-01 | High | XML | `ET.fromstring` без защиты от `DOCTYPE`/`ENTITY` — внутренние сущности могут раздуть документ (billion laughs) | `xmlutil.parse_xml` отклоняет директивы до разбора; тесты на бомбы |
| SEC-02 | High | HTTP | `ThreadingHTTPServer(("0.0.0.0", ...))` по умолчанию отдавал сейвы и API всей локальной сети | bind по умолчанию `127.0.0.1`, явный `--host 0.0.0.0` для осознанного шаринга |
| SEC-03 | Medium | HTTP | Заголовок `Server` раскрывал версию Python; не было CSP/Referrer-Policy | `server_version = "StardewTracker"`, `sys_version = ""`, CSP, `Referrer-Policy`, `nosniff` |
| SEC-04 | Medium | HTTP | Не было проверки, что CORS действительно закрыт | тесты `OPTIONS` и отсутствия `Access-Control-Allow-Origin` |
| BUG-01 | High | Watcher | `SaveError(SystemExit)` не ловился `except Exception`, поток наблюдателя умирал при исчезновении/блокировке сейва | явный `except SaveError` + тест жизненного цикла |
| BUG-02 | High | Multiplayer | `deep(root, "farmhands", limit=4000)` пропускал `farmhands`, если тег стоял после длинного `<player>` | сначала прямой дочерний элемент, затем неограниченный deep-lookup; тест с 4500 узлами |
| BUG-03 | High | Perfection | Farmer Level считался как `(сумма навыков + luck) // 2`; удача не входит в формулу игры, перфекция завышалась | формула только по пяти навыкам; в тестовый сейв добавлена `luckLevel=4` как регрессия |
| BUG-04 | High | Cache | Кэши `_PARSE_CACHE`/`_STATE_CACHE` без блокировок; кэш состояния возвращал общие вложенные списки; параллельные запросы могли дублировать разбор | RLock + LRU, сериализация разбора, deepcopy при выдаче состояния, тесты на 12 потоков |
| BUG-05 | Medium | Persistence | `report.html` писался напрямую — при обрыве оставался битый файл | атомарная запись `tmp + fsync + os.replace` |
| BUG-06 | Medium | Data | Повреждённый `data/*.json` давал голый `JSONDecodeError`/трейс | `DataError` с путём и шагами решения |
| BUG-07 | Medium | Save finder | Повторное сканирование стандартных папок, разное поведение при ошибках доступа | дедупликация по `realpath`, `strict`-режим для явного пути и мягкий для автопоиска |
| BUG-08 | Medium | State | `Handler` был глобальным синглтоном; сейв переключался до успешного разбора | `TrackerApp` на сервер, `activate()` меняет сейв только после успеха |
| BUG-09 | Low | Render | Кэш base64-спрайтов был ключом по имени файла, а не по пути | ключ по абсолютному пути |
| BUG-10 | Low | Goals | `save_goals` использовал фиксированный `.tmp` — гонка при параллельных сохранениях | `mkstemp`, `fsync`, `GOALS_LOCK` |
| QUAL-01 | High | Архитектура | Монолит 2114 строк, циклические обязанности, сложно тестировать по частям | пакет из 20 модулей по ответственности, `tracker.py` — совместимый фасад |
| AQA-01 | Medium | Тесты | Не покрыты окна времени, XML-безопасность, PNG-кодек, конкурентность, CLI, жизненный цикл сервера | +71 тест, покрытие 90% |
| AQA-02 | Medium | CI | flake8 необязателен, нет mypy/bandit/coverage/форматирования | quality-job с жёсткими гейтами |
| A11Y-01 | Low | Frontend | CSP отсутствовал; inline-JS не проверялся синтаксически | CSP + `node --check` в тестах |

### 4.1. Что проверено и признано корректным

- **XSS в шабоне:** динамические названия предметов/NPC/фермы проходят через `esc()` или
  `textContent`; JSON состояния экранирует `</`; добавлен тест на `</script>`.
- **Path traversal:** `/assets/sprites/` использует `basename` и белый список имён; тест
  `../../tracker.py` возвращает 404.
- **Выбор чужого сейва:** `/api/saves/select` и `?save=` принимают только пути из найденных
  сейвов и соседних папок; тест на файл вне списка даёт 403.
- **Валидация POST:** лимит 1 МБ, обязательный `application/json`, проверка формы `goals`,
  `tasks`, `annotations`; тесты 400/413/415.
- **Секреты/приватность:** приложение не делает исходящих запросов, внешних CDN в шаблоне нет,
  `goals.json`/`saves/`/`report.html` исключены из git.
- **Данные:** 74 рыбы, 95 музейных предметов, 155 товаров, 81 блюдо, 150 рецептов, 34 NPC,
  31 бандл, 12 целей гильдии; перекрёстные ссылки справочников проверяются тестом.

## 5. Архитектура после рефакторинга

```text
tracker.py                  совместимый CLI-фасад (python tracker.py ...)
stardew_tracker/
  __init__.py               публичный API и версия
  __main__.py               python -m stardew_tracker
  version.py                единый источник версии
  paths.py                  пути проекта и standalone-сборки (sys._MEIPASS, каталог данных ОС)
  constants.py              сезоны, навыки, звёздные капли, обелиски, спрайты
  errors.py                 SaveError / DataError
  xmlutil.py                namespace-хелперы + безопасный разбор XML
  timeutil.py               игровые часы, даты, окна времени, погода
  savefinder.py             поиск сейвов и валидация файлов
  saveparser.py             XML → сырые данные (кэш, блокировки)
  gamedata.py               data/*.json с кэшем и понятными ошибками
  goals.py                  goals.json, .bak, атомарная запись
  catalog.py                карточки/строки предметов
  collections.py            рыба, музей, отправка, рецепты, люди, бандлы, гильдия
  perfection.py             официальная формула 1.6 и счётчики
  today.py                  раздел «Сегодня»
  state.py                  оркестрация + кэш состояния
  render.py                 шаблон, inline-спрайты, атомарный отчёт
  server.py                 TrackerApp, HTTP API, watcher, serve
  cli.py                    info/build/open/serve, --host/--out/--version
build_data.py               офлайн-сборщик data/ и PNG-атласов (без изменений по смыслу)
packaging/                  spec PyInstaller и build_app.py (standalone-сборка)
assets/dashboard.html       интерфейс (inline CSS/JS)
tests/                      129 тестов: интеграция, юниты, безопасность, PNG, JS, lifecycle, сборка
```

Поток данных: `find_saves → parse_save (кэш) → collections/perfection/today → state (кэш) →
render/HTTP`. Пакет не тянет внешних зависимостей, Python 3.9+.

## 6. AQA: что добавлено

| Файл | Что проверяет |
|---|---|
| `tests/test_tracker.py` | справочники, полный разбор сейва, перфекция, кэши, рендер, HTTP-контракт, ошибки API |
| `tests/test_units.py` | время/погода, XML-хелперы и бомбы, поиск сейвов, goals, data-загрузчик, каталог, перфекция, рендер, CLI, конкурентность, мультиплеер |
| `tests/test_build_data.py` | PNG roundtrip (RGBA/индексированный/&gt;256 цветов), blit, item_group, unlock, Resolver |
| `tests/test_frontend_js.py` | синтаксис inline-JS через `node --check`, отсутствие inline-обработчиков и внешних URL |
| `tests/test_server_lifecycle.py` | `serve`, режим ожидания, watcher, коды выхода CLI |
| `tests/test_responsive_styles.py` | адаптивность/доступность шаблона (расширен, исправлено неиспользуемое значение) |
| `tests/test_packaging.py` | frozen-пути `sys._MEIPASS`, каталоги данных Windows/macOS/Linux, состав PyInstaller-спеки |

Особое внимание — регрессиям найденных багов:

- `test_farmhands_found_after_long_player_node` — 4500 узлов до `farmhands`;
- `test_perfection_and_today_panels` — Farmer Level = 22 при `luckLevel=4`;
- `test_state_cache_does_not_leak_mutations` — мутация выдачи не меняет кэш;
- `test_parallel_parse_and_state` — 12 потоков получают один объект разбора;
- `test_doctype_and_entity_are_rejected` — XML-бомбы;
- `test_watch_rebuilds_state_after_save_change` — наблюдатель жив и обновляет состояние;
- `test_refresh_failure_returns_structured_error` — ошибка API не роняет сервер.

## 7. Остальные риски и рекомендации

1. **`GET /api/refresh` меняет состояние.** CORS закрыт, ответы не читаются чужим origin, но
   для строгой защиты стоит перевести refresh на POST с токеном. Пока риск низкий: сервер по
   умолчанию слушает loopback.
2. **Нет аутентификации.** Осознанный `--host 0.0.0.0` открывает API локальной сети; в README
   это помечено. Для публичного доступа нужен реверс-прокси с авторизацией.
3. **CSP разрешает `'unsafe-inline'`.** Архитектура встраивает состояние и стили в HTML;
   полный отказ потребует nonce/внешних файлов и сломает автономный `report.html`.
4. **Кэш состояния не инвалидируется при изменении `data/*.json`.** Данные статичны; после
   пересборки справочников нужен перезапуск или «Обновить». Можно добавить mtime в ключ.
5. **`build_data.py` остаётся монолитом без типов.** Он запускается редко; следующий шаг —
   вынести PNG-кодек и резолвер локализации в отдельные модули.
6. **Версионирование `goals.json`.** Сейчас структура нормализуется «на лету»; стоит добавить
   `schema_version`, чтобы будущие миграции были предсказуемыми.
7. **Windows-специфика не в CI.** Пути и `%APPDATA%` покрыты юнит-тестами, но реальный Windows
   runner был бы полезен.
8. **`docs/index.html` — сгенерированный артефакт.** Он может отставать от шаблона; стоит
   добавить CI-проверку пересборки или генерировать его в релизе.
9. **HTML-тесты строковые.** `test_responsive_styles.py` проверяет наличие селекторов, а не
   рендер в браузере. Для дальнейшего роста — Playwright-скриншоты (опционально, вне runtime).
10. **Формат сейвов модов.** Парсер терпим к незнакомым тегам, но модовые поля не тестируются;
    при необходимости — фикстуры реальных сейвов 1.5/1.6.

## 7a. Повторное ревью (2026-11-10, v0.3.0)

Ручное QA и сверка данных со Stardew Valley Wiki (страницы Perfection, Collections, Crafting,
Cooking, Quests). Подробности — в `CHANGELOG.md`.

| ID | Приоритет | Находка | Исправление |
|---|---|---|---|
| DATA-01 | High | Коллекция рыбы 74 вместо 72: учитывались «легендарные II» и не учитывались медузы 1.6 → неверная перфекция | медузы добавлены, «легендарные II» помечены `extended` и исключены из счётчиков |
| DATA-02 | High | Полная отправка 155 вместо 154 (Гребешок в 1.6 — рыба) | `372` убран из `shipping.json` |
| DATA-03 | Medium | Рыба Ночного рынка «доступна» круглый год; у Лавового угря нет 100-го этажа | расписание зима 15–17, локация добавлена (и в `build_data.py`) |
| DATA-04 | Medium | Источники 53 рецептов — «Магазин / Событие», 34 блюд — «Level / TV (N)» | `data/recipe_sources.json` |
| DATA-05 | Low | Названия в новых текстах расходились с официальной локализацией (Ци/Ки, юнимо/джунимо) | исправлено, тест на официальные названия |
| BUG-11 | Medium | `allowed_save_paths` → `UnboundLocalError` при `SaveError` | начальное значение + тест |
| BUG-12 | Low | `kid() or kid()` для `Element` (пустой `<stats/>`) | явная проверка `is None` + тест |
| BUG-13 | Low | `norm_id("(O")` → `IndexError` | проверка `)` + тест |
| BUG-14 | Low | Ошибка диска при записи целей → 400 | 500 |
| BUG-15 | Low | `build_data.find_file` в Windows | нормализация разделителей |
| UI-01 | Medium | `/api/saves` на каждый символ поиска; «null дн.»; «26:00»; «Скрыть готовое» + «Готово» = пусто; гонка пометок с автообновлением | кэш, проверки, форматирование времени, удаление кнопки, счётчик незавершённых сохранений |
| UX-01 | High | Тёмная «болотная» палитра утомляет; цвета захардкожены в ~200 местах | токены темы, светлая/тёмная/системная темы, тест на отсутствие hex вне блоков темы |

Внешние ссылки на вики в danger zone — обычные `<a target="_blank" rel="noopener noreferrer">`
из данных: приложение не делает запросов само, `Referrer-Policy: no-referrer` сохраняется.

## 8. Как воспроизвести проверки

```bash
# runtime-тесты (без зависимостей)
python3 -m unittest discover -s tests -v

# quality-гейты
python3 -m pip install -r requirements-dev.txt
ruff check .
ruff format --check stardew_tracker tracker.py tests packaging/build_app.py
mypy
bandit -q -r stardew_tracker tracker.py build_data.py
coverage run -m unittest discover -s tests
coverage report

# синтетический сейв и CLI
python3 tests/make_test_save.py /tmp/saves
python3 tracker.py info --saves-dir /tmp/saves
python3 tracker.py build --saves-dir /tmp/saves --out /tmp/report.html
python3 tracker.py serve --saves-dir /tmp/saves --no-open

# standalone-сборка (артефакт dist/StardewTracker или .exe)
python3 -m pip install -r requirements-build.txt
python3 packaging/build_app.py
dist/StardewTracker --version
```

Дифференциальная проверка поведения:

```bash
git worktree add /tmp/orig ef22c6d
# собрать state/HTML старой версией и новой, сравнить с точностью до meta.generated
```
