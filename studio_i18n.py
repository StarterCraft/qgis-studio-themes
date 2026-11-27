"""Translations of the plugin's own texts (for now the ribbon's: its tabs,
group names, button labels and tooltips).

The language is QGIS's user interface language (Settings > Options >
General > Override system locale, else the system's), read once: QGIS
needs a restart to change it anyway. Texts are looked up by their English
original, in a context, since one English word can need two translations
(the "Select" group holds the "Select" button: "Выделение", "Выделить"):

- "title": tab and group names (studio_ribbon.TABS);
- "label": button labels (studio_ribbon.LABELS_BY_NAME);
- "text": other texts (tooltips, window titles).

A text with no translation in a language listed here: tr() gives the
English one, label() None, so the ribbon uses QGIS's own (translated) text
of the action instead of English. To add a language, add a dict like RU to TRANSLATIONS
under its two-letter code.
"""
import functools

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QLocale

RU = {
    "title": {
        # Tabs.
        "Project": "Проект", "Home": "Главная", "Data": "Данные", "Layer": "Слой", "Edit": "Правка",
        "Modify": "Изменение", "Annotate": "Аннотации", "View": "Вид", "Vector": "Вектор", "Raster": "Растр",
        "Mesh": "Сетка", "Processing": "Обработка", "GPS": "GPS", "Plugins": "Модули", "Settings": "Настройки",
        "Help": "Справка",
        # Groups.
        "Import and Export": "Импорт и экспорт", "Layouts": "Макеты", "More": "Ещё", "Navigate": "Навигация",
        "Select": "Выделение", "Inspect": "Сведения", "Add Data": "Добавить данные", "Add Layer": "Добавить слой",
        "Create Layer": "Создать слой", "More Data": "Ещё данные", "Copy and Paste": "Копирование",
        "Overview": "Обзор", "Editing": "Редактирование", "Digitize": "Оцифровка", "Features": "Объекты",
        "History": "История", "Snapping": "Прилипание", "Shapes": "Фигуры", "Advanced": "Расширенная",
        "Transform": "Трансформация", "Rings and Parts": "Кольца и части", "Reshape": "Изменение формы",
        "Point Symbols": "Точечные знаки", "Labels": "Подписи", "Label Tools": "Инструменты подписей",
        "Annotations": "Аннотации", "Draw": "Рисование", "Map Annotations": "Аннотации карты",
        "Map Views": "Карты", "Bookmarks": "Закладки", "Time": "Время", "Elevation": "Высоты",
        "Map Display": "Отображение", "Window": "Окно", "Vector Tools": "Векторные инструменты",
        "Vector Plugins": "Векторные модули", "Tools": "Инструменты", "Raster Tools": "Растровые инструменты",
        "Stretch": "Растяжение", "Adjust": "Коррекция", "Raster Plugins": "Растровые модули",
        "Calculator": "Калькулятор", "Mesh Editing": "Правка сетки", "Toolbox": "Инструменты",
        "Results": "Результаты", "Connection": "Подключение", "Tracking": "Трек", "Display": "Отображение",
        "Python": "Python", "Plugin Menus": "Меню модулей", "Database": "База данных", "Web": "Веб",
        "Options": "Параметры", "Customize": "Настройка", "Profiles": "Профили", "QGIS": "QGIS",
        "Community": "Сообщество",
        # Groups the ribbon makes itself (Plugins tab).
        "Menus": "Меню", "Plugin": "Модуль",
    },
    "label": {
        "New": "Создать", "Open": "Открыть", "Save": "Сохранить", "New Layout": "Новый макет",
        "Layouts": "Макеты", "Style Manager": "Менеджер стилей",
        "Select": "Выделить", "Deselect": "Снять выделение", "Reselect": "Выделить снова",
        "Zoom In": "Увеличить", "Zoom Out": "Уменьшить", "Full Extent": "Полный охват",
        "Identify": "Определить", "Attribute Table": "Таблица атрибутов", "Field Calculator": "Калькулятор полей",
        "Statistics": "Статистика", "Toolbox": "Инструменты", "Measure": "Измерить", "Map Tips": "Подсказки",
        "Actions": "Действия",
        "Data Source Manager": "Источники данных",
        "Vector": "Вектор", "Raster": "Растр", "Mesh": "Сетка", "Delimited Text": "Текст с разделителями",
        "SpatiaLite": "SpatiaLite", "Virtual": "Виртуальный", "Database": "База данных", "WMS/WMTS": "WMS/WMTS",
        "WCS": "WCS", "WFS": "WFS", "STAC": "STAC", "Other Layer": "Другой слой",
        "GeoPackage Layer": "Слой GeoPackage", "Shapefile": "Shapefile", "Scratch Layer": "Временный слой",
        "Mesh Layer": "Слой сетки", "Virtual Layer": "Виртуальный слой",
        "Toggle Editing": "Режим правки", "Save Edits": "Сохранить правки", "All Edits": "Все правки",
        "Add Feature": "Добавить объект", "Vertex Tool": "Вершины", "Digitize Mode": "Режим оцифровки",
        "Edit Attributes": "Изменить атрибуты", "Delete": "Удалить", "Cut": "Вырезать", "Copy": "Копировать",
        "Paste": "Вставить", "Undo": "Отменить", "Redo": "Повторить",
        "Advanced Digitizing": "Расширенная оцифровка",
        "Move": "Переместить", "Rotate": "Повернуть", "Scale": "Масштабировать", "Simplify": "Упростить",
        "Offset Curve": "Смещение линии", "Reverse Line": "Развернуть линию",
        "Add Ring": "Добавить кольцо", "Add Part": "Добавить часть", "Fill Ring": "Заполнить кольцо",
        "Delete Ring": "Удалить кольцо", "Delete Part": "Удалить часть",
        "Reshape": "Изменить форму", "Chamfer/Fillet": "Фаска/скругление", "Trim/Extend": "Обрезать/продлить",
        "Split Features": "Разрезать объекты", "Split Parts": "Разрезать части",
        "Merge Features": "Объединить объекты", "Merge Attributes": "Объединить атрибуты",
        "Point Symbols": "Точечные знаки",
        "Labels": "Подписи", "Diagrams": "Диаграммы", "Pinned Labels": "Закреплённые",
        "Unplaced Labels": "Неразмещённые", "Pin/Unpin": "Закрепить", "Show/Hide": "Показать/скрыть",
        "Properties": "Свойства",
        "Annotation Layer": "Слой аннотаций", "Edit Nodes": "Правка узлов", "Map Annotations": "Аннотации карты",
        "New Map View": "Новая карта", "New 3D Map View": "Новая 3D-карта", "New Bookmark": "Новая закладка",
        "Bookmarks": "Закладки", "Temporal Controller": "Управление временем",
        "Raster Calculator": "Калькулятор растров", "Georeferencer": "Привязка растров",
        "Mesh Calculator": "Калькулятор сеток",
        "Connect": "Подключить", "Recenter": "Центрировать", "Destination Layer": "Целевой слой",
        "Add Vertex": "Добавить вершину", "Create Feature": "Создать объект", "Reset Track": "Сбросить трек",
        "Information": "Информация", "Settings": "Настройки", "Python Console": "Консоль Python",
        # Menu commands and menus.
        "Save As": "Сохранить как", "Revert": "Вернуть", "Close": "Закрыть", "Exit QGIS": "Выход",
        "From Template": "Из шаблона", "Recent": "Недавние", "Open From": "Открыть из", "Save To": "Сохранить в",
        "Snapping Options": "Параметры прилипания", "Export Image": "Экспорт в изображение",
        "Export PDF": "Экспорт в PDF", "Export DXF": "Экспорт в DXF", "Import DWG/DXF": "Импорт DWG/DXF",
        "New Report": "Новый отчёт", "Open Layout": "Открыть макет", "Project Models": "Модели проекта",
        "Paste As": "Вставить как", "New 3D Globe": "Новый 3D-глобус", "Manage 3D Views": "Управление 3D-картами",
        "Bookmark Manager": "Менеджер закладок", "Elevation Profile": "Профиль высот",
        "Manage Profiles": "Управление профилями", "Elevation Controller": "Управление высотами",
        "Decorations": "Оформление", "Preview Mode": "Режим просмотра", "Layer Visibility": "Видимость слоёв",
        "Panels": "Панели", "Full Screen": "Полный экран", "Hide Panels": "Скрыть панели",
        "Map Only": "Только карта", "All Layer Types": "Все типы слоёв", "All New Layers": "Все новые слои",
        "Embed Layers": "Внедрить слои", "Layer Definition": "Описание слоя", "Layer Properties": "Свойства слоя",
        "Filter": "Фильтр", "Duplicate": "Дублировать", "Set Layer CRS": "Задать СК слоя",
        "Set Project CRS": "Задать СК проекта", "Scale Visibility": "Видимость по масштабу",
        "Save as Definition": "Сохранить описание", "Remove": "Удалить", "Copy Style": "Копировать стиль",
        "Paste Style": "Вставить стиль", "Copy Layer": "Копировать слой", "Paste Layer": "Вставить слой",
        "Show in Overview": "Показать в обзоре", "Show All": "Показать все", "Hide All": "Скрыть все",
        "Reindex": "Переиндексировать",
        "Processing": "Обработка", "Model Designer": "Конструктор моделей", "History": "История",
        "Results Viewer": "Результаты", "Edit In-Place": "Правка на месте", "Options": "Параметры",
        "Manage Plugins": "Управление модулями", "DB Manager": "Менеджер БД", "Query History": "История запросов",
        "Shortcuts": "Сочетания клавиш", "Customization": "Настройка интерфейса",
        "Custom CRS": "Пользовательская СК", "User Profiles": "Профили",
        "Help": "Справка", "C++ API": "C++ API", "PyQGIS API": "PyQGIS API", "Plugin Help": "Справка модулей",
        "Home Page": "Сайт QGIS", "Check Version": "Проверить версию", "About": "О программе",
        "Report Issue": "Сообщить об ошибке", "Get Involved": "Участвовать", "Support": "Поддержка",
        "Donate": "Пожертвовать", "Sponsors": "Спонсоры",
    },
    "text": {
        "Ribbon": "Лента",
        "Collapse the ribbon to its tabs (double-click a tab)":
            "Свернуть ленту до вкладок (двойной щелчок по вкладке)",
    },
}

TRANSLATIONS = {"ru": RU}


@functools.lru_cache(maxsize=1)
def language():
    """QGIS's user interface language as a two-letter code ("en", "ru"...)."""
    try:
        from qgis.core import QgsApplication  # pylint: disable=import-outside-toplevel
        name = QgsApplication.locale()
    except (ImportError, AttributeError, RuntimeError):
        name = ""
    if not name:
        settings = QgsSettings()
        overridden = settings.value("locale/overrideFlag", False, type=bool)
        name = settings.value("locale/userLocale", "", type=str) if overridden else ""
        name = name or QLocale().name()
    return (name or "en").replace("-", "_").split("_")[0].lower()


def _table(context):
    return TRANSLATIONS.get(language(), {}).get(context, {})


def tr(text, context="text"):
    """`text` in QGIS's language, or as it is when it has no translation."""
    return _table(context).get(text, text) if text else text


def label(text):
    """A button label in QGIS's language. None when the language has a
    translation here that misses this label: the action's own text,
    translated by QGIS, then fits the rest of the ribbon better than the
    English label. Languages with no translation here keep English labels."""
    if not text:
        return None
    if language() not in TRANSLATIONS:
        return text
    return _table("label").get(text)
