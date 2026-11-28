# Frontend — Скорая помощь

Документация по клиентской части проекта: шаблоны (`templates/`) и статика (`static/`). 

## Структура
templates/
base.html
_calls_results.html
calls_list.html
call_card.html
admin.html
admin_map_call.html
login.html
error.html
form.html
patient_card.html
patient_info_form.html
problems_form.html
case_form.html
diary_form.html
appointment_form.html
map_route.html
map_action.html

static/
css/
base.css
calls_list.css
call_card.css
admin.css
admin_map_call.css
auth.css
form.css
appointment_form.css
patient_card.css
map_route.css
map_action.css
js/
base.js
calls_list.js
call_card.js
admin_map_call.js
form.js
map_route.js
patient_card.js
map_action.js
sw.js
img/
icons/
ambulance.png
ambulance.svg
ban.png
check-circle.png
clipboard.png
doctor.png
home.png
list.svg
logout.png
map.svg
patient.jpg
phone.png
pin.png
refresh.png
route.png
settings.png
shield.png
target.png
video/
home-bg.mp4
home-bg.jpg
login-bg.mp4
login-bg.jpg


## Шаблоны

### `base.html`
Базовый каркас всех страниц. Содержит:
- `<head>` с viewport, meta `csrf-token`, ранним скриптом применения темы/размера шрифта/UI-режима из `localStorage`;
- шапку `.app-header` (меню пользователя, часы, индикатор сети);
- область флеш-сообщений `#flash-area`;
- `<main class="app-main">` с блоком `content`;
- панель настроек `#settings-panel` (тема, размер текста, режим интерфейса, часы, крупные контролы, контраст);
- подключение `base.css`, `base.js` и блоков `css` / `js` для дочерних шаблонов.

Блоки, доступные для переопределения:
- `title` — заголовок вкладки;
- `body_class` — класс на `<body>` (например, `is-home`, `is-login`, `is-admin`);
- `bg_video` — фоновое видео для конкретной страницы (главная и вход); подключается как `<video class="bg-video" autoplay muted loop playsinline>` с постером;
- `css` — дополнительные стили;
- `content` — основной контент;
- `js` — дополнительные скрипты.

### `_calls_results.html`
Партиал со списком карточек вызовов и пагинацией. Рендерится внутри `calls_list.html` и подгружается через `/search` при фильтрации и постраничном переходе. Содержит:
- `#calls-container` с карточками `.call-card`;
- бейдж приоритета, номер вызова, причина, пациент, мета-строка (адрес, телефон, расстояние);
- блок действий в зависимости от роли и состояния вызова (взять, открыть, «взят другим», завершён);
- таймстемпы для админа на активном вызове;
- пагинацию `#pagination`.

### `calls_list.html`
Главная страница. Для роли `doctor`:
- `active-call-hero` — текущий активный вызов;
- `doctor-idle-banner` — если активного вызова нет.

Общие элементы:
- панель действий (`#map-toggle-btn`, `#list-toggle-btn`, `#sort-distance-btn`, `#refresh-btn`);
- форма поиска и фильтров (`#search-form`, `#filters-toggle`, `#filters-menu` с полем поиска, приоритетом и сортировкой);
- контейнер результатов `#content-area` / `#results`;
- контейнер карты `#map-shell` с картой Leaflet `#map`, слоями и метриками;
- фоновое видео `#home-bg-video` (`home-bg.mp4`, постер `home-bg.jpg`), скорость `0.5`, поверх — затемняющий оверлей `body.is-home::before`.

### `call_card.html`
Карточка вызова. Секции:
- шапка с причиной, пациентом, приоритетом и расстоянием;
- `dl.form-fields` — адрес, телефон, срочность, состояние;
- уведомление о статусе (завершён, ваш активный, взят другим, есть другой активный);
- этапы бригады (`.stages`) для своего активного вызова с кнопками «В путь» / «Прибыл», маршрут, карточка пациента;
- записи (информация, проблемы, случаи, дневник) в `details.record-group` с подсветкой некорректных и удалением для админа;
- блок завершения (завершить / ложный);
- блок действий для свободного вызова (взять, карточка пациента);
- блок для остальных (карточка пациента, показать на карте для админа).

Права на просмотр и добавление записей считаются в шаблоне через `can_view_records` и `can_add_records`.

### `admin.html`
Панель администратора:
- `admin-hero` с профилем;
- `stats-grid` — 4 карточки сводки (завершено, ложные, в работе, всего);
- `admin-layout` — сетка из основной колонки и сайдбара;
- основная колонка: `users-grid` с карточками пользователей и кнопкой «+ Добавить», скрытая форма создания пользователя `#create-user-section`;
- сайдбар: `history-list` с историей вызовов, каждый элемент — ссылка на карточку вызова.

### `admin_map_call.html`
Наблюдение за вызовом на карте:
- `watch-hero` — заголовок, пациент, адрес, приоритет, расстояние;
- `watch-info` — статус, этап, машина, маршрут;
- `watch-map-frame` / `watch-map-square` / `#watch-map` с data-атрибутами для Leaflet.

### `login.html`
Страница входа:
- `body_class = is-login`, фоновое видео `#login-bg-video` (`login-bg.mp4`, постер `login-bg.jpg`), скорость `0.2`, «заморозка» на 12-й секунде на 60 секунд, поверх — оверлей `body.is-login::before` с цветом под тему;
- двухколоночный `auth-shell`: визуальная панель и карточка формы;
- форма с CSRF, логином и паролем, переключателем видимости пароля;
- скрипт: переключение пароля, управление скоростью и «заморозкой» фонового видео.

### `error.html`
Страница ошибки с кодом, сообщением и кнопкой возврата на главную.

### `form.html`
Универсальная форма с одним текстовым полем. Используется как заглушка/общая форма.

### `patient_card.html`
Карточка пациента:
- поля (дата рождения, пол, ОМС, телефон);
- аллергии;
- кнопка записи на приём;
- список записей на приём.

### `patient_info_form.html`, `problems_form.html`, `case_form.html`, `diary_form.html`
Формы добавления записей к вызову. Различаются набором полей:
- информация — тип, описание;
- проблемы — тип, описание;
- случай — тип, описание, результат;
- дневник — тип, запись.

Все формы поддерживают offline-очередь через `data-offline-queue`.

### `appointment_form.html`
Форма записи на приём: дата, время, врач, комментарий. Скрытые `patient_id` и CSRF, offline-очередь.

### `map_route.html`
Маршрут к вызову:
- `#route-status` — статус построения;
- `#route-map` — карта Leaflet;
- кнопки «Повторить геолокацию», «Указать на карте», «Перестроить маршрут»;
- `<script id="route-data" type="application/json">` с координатами и адресом.

### `map_action.html`
Промежуточная страница действий по вызову: маршрут, данные пациента, возврат.

## CSS

Все файлы используют токены из `base.css` (`--bg`, `--bg-card`, `--text`, `--primary`, `--surface`, `--surface-blur`, `--radius`, `--transition` и т.д.). Размер шрифта управляется через `html[data-font-size]`, тема — через `html[data-theme]`, UI-режим — через `html[data-ui-mode]`.

### `base.css`
- CSS-переменные для трёх тем (`dark`, `light`, `gray`);
- масштаб шрифта через `:root font-size` + `html[data-font-size="1.2/1.5/2"]`;
- глобальный layout: `html, body, .app-scale` высотой `100%`, `.app-main` — flex-колонка с внутренним скроллом;
- шапка, меню пользователя, часы, индикатор сети;
- флеш-сообщения, кнопки, notice, панель настроек;
- стили `body.is-home`, `body.is-login`, `body.is-admin`, `body.is-patient`, `body.is-call`, `body.is-route`;
- фоновое видео и оверлеи: `.bg-video` — фиксированное позиционирование, `object-fit: cover`, `opacity: 0.4`; на главной дополнительно `filter: blur(4px) brightness(0.3) saturate(1.5)`; при `≤ 900px` и `prefers-reduced-motion` видео скрывается;
- режим `data-ui-mode="simple"` (без анимаций, теней, blur);
- иконки `.inline-icon`, `.icon`, `.ambulance-marker img`;
- компактный режим для `data-font-size="1.5"` и `"2"`.

### `calls_list.css`
- `page-hero`, панель действий, форма поиска и фильтров;
- карточки вызовов `.call-card` с акцентной полосой приоритета, градиентным фоном, hover-свечением, чипом номера, мета-строкой и бейджами;
- таймстемпы, пагинация;
- карта: `map-page`, `map-page-body`, `map-square`, `map-container`, попапы;
- `active-call-hero`, `doctor-idle-banner`.

### `call_card.css`
- `form-card`, шапка, поля, заметки;
- этапы `.stages`;
- записи `.record-group`, `.record-list`, `.record-item`, некорректные и удаление;
- блоки `form-section-stage`, `form-section-records`, `form-section-finish`.

### `admin.css`
- `admin-hero`, `admin-profile`;
- `stats-grid`, `stats-card`;
- `admin-layout`, `users-grid`, `user-card`, `history-list`;
- форма создания пользователя `.admin-form`.

### `admin_map_call.css`
- `watch-hero`, `watch-info`, `watch-map-frame`, `watch-map-square`, `watch-map`;
- `.ambulance-marker`.

### `auth.css`
- `login-lock`, `auth-shell`, `auth-visual` (градиент, сетка, крест, пульс);
- `auth-card`, поля, кнопка, футер;
- адаптив для мобильных.

### `form.css`
- общие поля `.form-textarea`, `.form-select`, `.form-label`;
- offline-баннер `.form-offline-banner`.

### `appointment_form.css`
- переопределение вида `input[type="date"]` и `input[type="time"]`;
- цвет иконки календаря/часов под тему.

### `patient_card.css`
- `patient-header`, `patient-fields`, `patient-alert`, `patient-actions`;
- список записей на приём.

### `map_route.css`
- `route-status`, `route-map` (высота с уменьшением на крупном шрифте), `route-actions`, `route-hint`;
- `.ambulance-marker`.

### `map_action.css`
- `map-action-page`, заголовок, пациент, адрес, расстояние;
- вертикальный список кнопок.

## JavaScript

### `base.js`
- блокировка pinch-зума и двойного тапа, разрешение Ctrl+± и Ctrl+колеса;
- индикатор сети (`#net-status`);
- меню пользователя `#app-user-btn` / `#app-user-dropdown`;
- флеш-сообщения: появление, авто-скрытие, клик-скрытие, `window.showFlash`;
- настройки в `localStorage` (`app_settings_v1`): тема, размер шрифта, часы, авто-тема, крупные контролы, контраст, UI-режим;
- `applySettings()` применяет тему, шрифт, UI-режим, состояние кнопок и чекбоксов; при смене шрифта диспатчит `fontsizechange`;
- часы в шапке;
- панель настроек: открытие/закрытие, обработчики кнопок темы, размера, UI-режима, чекбоксов, сброс.

### `calls_list.js`
- поиск с дебаунсом 300 мс и отменой предыдущего запроса (`AbortController`);
- маска телефона: ввод только цифр, вставка, backspace, отображение маски;
- фильтры: поле, приоритет, сортировка; сохранение поля в `localStorage`;
- пагинация без перезагрузки через `/search`;
- карта Leaflet: инициализация, слои (машины, вызовы, на вызове), метрики;
- маркеры вызовов с попапами и подтверждением взятия двойным кликом;
- маркеры машин с попапами и маршрутами;
- геолокация фельдшера;
- авто-обновление карты раз в 8 секунд;
- `fontsizechange` → `map.invalidateSize()`.

### `call_card.js`
- защита от двойного клика по кнопкам `.call-actions .btn`;
- двойной клик по записи `[data-mark-url]` → подтверждение и POST-форма с CSRF для отметки «некорректная».

### `admin_map_call.js`
- карта Leaflet для наблюдения за вызовом;
- маркер вызова, маркер машины (иконка `ambulance.svg`);
- построение маршрута через OSRM с fallback на прямую линию;
- `fontsizechange` → `map.invalidateSize()`.

### `form.js`
- offline-очередь `pending_forms` в `localStorage`;
- показ баннера при отсутствии сети;
- при submit онлайн — обычный POST, офлайн — сохранение в очередь;
- при появлении сети — отправка очереди, обработка 400 (протухший CSRF), флеш-сообщения.

### `map_route.js`
- карта Leaflet, маркер цели;
- запрос геолокации, watchPosition;
- ручное указание точки кликом по карте;
- построение маршрута через OSRM, таймаут 6 секунд, fallback на прямую линию;
- перестроение по кнопке и раз в 20 секунд;
- `fontsizechange` → `map.invalidateSize()`;
- очистка таймеров и watch при `beforeunload`.

### `patient_card.js`
- индикация загрузки кнопки записи на приём.

### `map_action.js`
Пустой файл, логика перенесена в `map_route.js`.

### `sw.js`
- кэши `local-tiles-v1` и `local-static-v2`;
- `install` — `skipWaiting`, `activate` — удаление старых кэшей и `clients.claim`;
- стратегии: `cacheFirst` для `/tiles/` и `/vendor/leaflet/`, `staleWhileRevalidate` для `/static/css/` и `/static/js/`.

## Видео

Фоновые видео используются на двух страницах: главная (`calls_list.html`) и вход (`login.html`). Видео декоративные, не несут смысловой нагрузки, отключаются на мобильных и при `prefers-reduced-motion`.

### Файлы
static/video/
home-bg.mp4 фоновое видео главной страницы
home-bg.jpg постер (превью) для home-bg.mp4
login-bg.mp4 фоновое видео страницы входа
login-bg.jpg постер (превью) для login-bg.mp4


Постеры (`*.jpg`) показываются до загрузки видео и на устройствах, где видео отключено.

### Подключение

Видео подключается через блок `bg_video` в `base.html`. На каждой странице свой `<video>`:

```html
<video id="home-bg-video" class="bg-video" autoplay muted loop playsinline preload="auto"
       poster="{{ url_for('static', filename='video/home-bg.jpg') }}">
  <source src="{{ url_for('static', filename='video/home-bg.mp4') }}" type="video/mp4">
</video>
