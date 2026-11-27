"""The ribbon: QGIS's toolbars as tabs of grouped buttons (Plugins > QGIS
Studio Themes > Settings > Interface).

A row in place of the menu bar holds the tabs (Project, Home, Layer...),
with Help and a collapse button at their right, and under them the current tab's
page, a surface of its own the current tab opens into (a folder tab, its
name underlined in the accent): groups of large buttons (a 28 px icon, the
label under it) and small ones (20 px icons, labelled or not) in rows,
each group named in small capitals beneath. The sizes are ones the icons
are pre-rendered at, so every icon is pixel-sharp.

Every action of every main window toolbar is on the ribbon, by
construction: TABS places QGIS's toolbars, a group listing no actions
takes those of its toolbar no group names (so actions plugins add to
QGIS's toolbars land there too), and any other toolbar (a plugin's, added
at any time) gets a group of its own on the Plugins tab. So is every
command of QGIS's menus: TABS places the ones on no toolbar, each menu's
"More" group shows what else it holds (what plugins add, at any time),
and menus plugins add to the menu bar get groups on the Plugins tab;
commands QGIS gives no icon get one of the theme's (ICON_FALLBACKS). The
menu bar itself is folded away. The buttons are
the toolbars' own actions (QToolButton.setDefaultAction), so their icons
(the theme's, swapped by the plugin), checked, enabled and visible states
follow QGIS's at no cost. QGIS's tool buttons that switch between tools
(Select, Measure, Vertex Tool...) are cloned, the chosen tool passed back
to QGIS's button, and widgets other than buttons (the snapping tolerance
and units) are borrowed from their hidden toolbar while the ribbon shows
and given back after.

The toolbars are hidden, not removed, so QGIS keeps their places: turning
the ribbon off shows the ones it hid (remembered across sessions, as QGIS
saves them hidden). Pages are built when first shown and again when their
toolbars change, so startup builds one page and nothing runs while the
ribbon simply shows; all styling comes from the theme's stylesheet
(style.qss, object names and the studioRibbon property).
"""
import os
import re

import yaml
from qgis.core import QgsSettings
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer
from qgis.PyQt.QtGui import QFont, QFontInfo, QFontMetrics, QIcon, QIconEngine, QPainter, QPalette, QPixmap
from qgis.PyQt.QtWidgets import (
    QAction, QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QScrollArea, QSizePolicy, QStackedWidget, QTabBar,
    QToolBar, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from . import studio_toolbars
from .studio_events import menu_of
from .studio_i18n import label as translated_label, tr

HOST_NAME = "studioRibbonHost"
# The tab shown, whether the ribbon is collapsed to its tabs, and the
# toolbars it hid (shown again when the ribbon is turned off, also in a
# later session: QGIS saves them hidden).
TAB_SETTING = "studio_themes/ribbonTab"
COLLAPSED_SETTING = "studio_themes/ribbonCollapsed"
HIDDEN_SETTING = "studio_themes/ribbonHiddenToolbars"
# Qt's "no maximum" widget size.
QWIDGETSIZE_MAX = (1 << 24) - 1

# Sizes (logical px): icons, the rows of small buttons and the groups'
# room. By default they follow QGIS's toolbar icon size (Settings > Options
# > General > Icon size), as the toolbars the ribbon stands for would; the
# ribbon's own size and density settings (RIBBON_SIZES, DENSITIES) can
# override that. Set by set_sizes, these values are those of QGIS's
# default 24 in standard density.
LARGE_ICON = 32
SMALL_ICON = 20
ROW_HEIGHT = 24
ROWS = 3
SPACING = 2
# The gap between rows of small buttons: SPACING, or more where a large
# button's two-line label needs the room (see ribbon_sizes).
ROW_SPACING = SPACING
BODY = ROWS * ROW_HEIGHT + (ROWS - 1) * ROW_SPACING
LARGE_MIN_WIDTH = 56
# A large button's room besides its icon and two label lines: its padding
# (style.qss), the gap Qt leaves under the icon and ICON_GAP (4).
LABEL_ROOM = 7 + 4
# The gap between a button's icon and its label: beside a small button's
# icon, under a large one's (an empty strip in the icon, _GapIcon).
ICON_GAP = 4
# The height of a two-line label in the UI font at the default size.
DEFAULT_LABEL = 30
# One label line (set_sizes): a large button with a one-line label moves its
# icon down by half of it, so icon and label sit centred on the rows instead
# of hanging from the top.
LABEL_LINE = DEFAULT_LABEL // 2
# style.qss's padding above and below a large button's icon and label, per
# density (QToolButton[studioRibbon="large"]).
LARGE_PADDING = {"standard": (4, 3), "compact": (3, 2)}
# Room around a group's buttons (left, top, right, bottom), per density:
# compact keeps less space above and below them, but enough that the icons
# and names do not touch the page's edges.
STANDARD_MARGINS = (6, 9, 6, 7)
COMPACT_MARGINS = (6, 6, 6, 6)
GROUP_MARGINS = COMPACT_MARGINS
# The ribbon's size (Settings > Ribbon size): "auto" follows QGIS's toolbar
# icon size; the others stand for that size set to 16, 24 or 32.
RIBBON_SIZES = {"auto": None, "small": 16, "medium": 24, "large": 32}
# Its density (Settings > Ribbon density): compact by default, keeping the
# icons' sizes and taking less room around them (rows, group margins, tabs),
# about as high as other ribbons; standard gives them more room.
DENSITIES = ("compact", "standard")
DEFAULT_DENSITY = "compact"
DENSITY = "compact"
# Compact tabs: their names at most this size (px), as other ribbons'.
COMPACT_TAB_FONT = 12
# Where the groups' names go and which name shows (Settings, in ribbon
# mode): the toolbar names' choices (studio_toolbars.POSITIONS,
# NAME_STYLES), names below the buttons by default, in full where they fit.
CAPTION_POSITION = "bottom"
CAPTION_NAMES = "auto"
# The gap between a name left of the buttons and the buttons.
SIDE_GAP = 6
# The largest icon of the buttons right of the tabs (Help), so a large
# ribbon size keeps the tab row low.
CORNER_ICON = 20


def ribbon_sizes(toolbar, compact=False, label=DEFAULT_LABEL):
    """(small icon, large icon, row height, row spacing, large button
    minimum width) for a toolbar icon size `toolbar`: small buttons a sixth
    smaller than a toolbar's (on a 4 px step, never below 16), large ones
    12 px larger (8 for the smallest), rows 4 px taller than their icons
    (2 px when `compact`). The rows are set further apart where a large
    button's icon and two-line label (`label` px high, by the UI font) need
    more than their height, so a label is never cut short. 16 gives 16, 24
    and 20; 24 gives 20, 32 and 24; 32 gives 28, 40 and 32."""
    small = max(16, round(toolbar * 5 / 6 / 4) * 4)
    large = small + (12 if small >= 20 else 8)
    row = small + (2 if compact else 4)
    need = large + LABEL_ROOM + label
    spacing = max(SPACING, -(-(need - ROWS * row) // (ROWS - 1)))
    return small, large, row, spacing, large + 24


def set_sizes(toolbar, density="standard", label=DEFAULT_LABEL):
    """Use the sizes for toolbar icon size `toolbar` in `density` with
    two-line labels `label` px high (see ribbon_sizes); True when they
    changed."""
    global SMALL_ICON, LARGE_ICON, ROW_HEIGHT, ROW_SPACING, BODY, LARGE_MIN_WIDTH  # pylint: disable=global-statement
    global GROUP_MARGINS, DENSITY, LABEL_LINE  # pylint: disable=global-statement
    LABEL_LINE = label // 2
    compact = density == "compact"
    sizes = ribbon_sizes(toolbar, compact, label)
    if sizes == (SMALL_ICON, LARGE_ICON, ROW_HEIGHT, ROW_SPACING, LARGE_MIN_WIDTH) and density == DENSITY:
        return False
    SMALL_ICON, LARGE_ICON, ROW_HEIGHT, ROW_SPACING, LARGE_MIN_WIDTH = sizes
    BODY = ROWS * ROW_HEIGHT + (ROWS - 1) * ROW_SPACING
    GROUP_MARGINS = COMPACT_MARGINS if compact else STANDARD_MARGINS
    DENSITY = density
    return True


# The current tab's top margin in style.qss (studioRibbonTabs::tab:top:selected),
# per density, and the room above the tab row.
TAB_TOP = 4
COMPACT_TAB_TOP = 2
BAR_TOP = 5
COMPACT_BAR_TOP = 2

# Layouts of a group's small buttons: labelled, or icons only; or (plugins'
# groups) large labelled buttons for up to AUTO_LARGE actions, else icons.
LABELS, ICONS, AUTO = "labels", "icons", "auto"
AUTO_LARGE = 3
# The most used commands of icon-only groups: labelled small buttons, in
# their own column(s) before the group's other (icon-only) buttons.
LABELLED_SMALL = frozenset(("mActionZoomIn", "mActionZoomOut", "mActionZoomFullExtent"))
# The tabs, in order: the profile's own ribbon.yaml (USER_TABS_FILE, saved
# by the ribbon editor, studio_ribbon_editor) when there is one and it reads,
# else the plugin's (TABS_FILE); read once, at startup. Their header
# describes the format. Read into (title, groups). A group: (title, sources,
# large, layout[, rows]). Sources are (toolbar objectName, action
# objectNames, or None for those of the toolbar no group names); ("@",
# objectNames) for actions of the main window not on a toolbar or menus;
# ("menu", menu objectNames) for what those menus hold that the ribbon has
# nowhere else (see StudioRibbon._covered); or (DROPDOWN, (action, title,
# items)) for a button of one's own opening a list (see _dropdown). Every command of QGIS's menus is
# on some tab, so the menu bar is folded away (set_menu_bar_folded).
TABS_FILE = os.path.join(os.path.dirname(__file__), "ribbon.yaml")
LAYOUTS = (LABELS, ICONS, AUTO)
# The tab plugins' toolbars and menus get groups on: every ribbon.yaml has it.
PLUGIN_TAB = "Plugins"
# A dropdown source: a button opening a list of commands and menus (a
# command of its own on its face, if it has one); SEPARATOR in its items
# draws a line.
DROPDOWN = "dropdown"
SEPARATOR = "-"
# A menu's name with CONTENTS after it, in a dropdown's items: the menu's
# own commands in the list itself, between lines, not as a submenu (e.g.
# the recent projects in Open's list); with TITLED after it, under a caption
# that is the menu's name (not clickable).
CONTENTS = "/*"
TITLED = "/*:title"


def item_menu(name):
    """The menu a dropdown item `name` shows the contents of, or None."""
    for suffix in (TITLED, CONTENTS):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return None


def item_titled(name):
    """Whether dropdown item `name` shows its menu's name above its commands."""
    return name.endswith(TITLED) and len(name) > len(TITLED)


# Texts of one's own, never clicked, in a group's rows or a dropdown's list:
# a caption (dimmed, semibold, as a dropdown's menu name) or a note (plain,
# dimmed). Their text may hold TEXT_VARIABLES, filled from the command or
# menu named in "for:": its label as the ribbon shows it, and its
# objectName.
CAPTION, NOTE = "caption", "note"
LABEL_KINDS = (CAPTION, NOTE)
TEXT_VARIABLES = ("{title}", "{id}")


def _label(kind, value, where):
    """A caption or note of ribbon.yaml as (kind, text or None, for or None)."""
    if isinstance(value, str):
        value = {"text": value}
    if not isinstance(value, dict):
        raise ValueError(f"{where}: {kind}: expected text: and for:")
    text, target = value.get("text"), value.get("for")
    for key, item in (("text", text), ("for", target)):
        if item is not None and (not isinstance(item, str) or not item):
            raise ValueError(f"{where}: {kind}: {key}: expected text")
    if text is None and target is None:
        raise ValueError(f"{where}: a {kind} needs a text: or a for:")
    return kind, text, target


def label_text(text, title, name):
    """A caption's or note's text with its variables filled: {title} the
    command's label, {id} its objectName; "{title}" without a text."""
    return (text if text is not None else "{title}").replace("{title}", title or "").replace("{id}", name or "")


def user_tabs_file():
    """The profile's own ribbon.yaml (studio_themes/ribbon.yaml in the QGIS
    profile folder), which the plugin's updates leave alone."""
    from qgis.core import QgsApplication  # pylint: disable=import-outside-toplevel
    return os.path.join(QgsApplication.qgisSettingsDirPath(), "studio_themes", "ribbon.yaml")


def _names(value, where):
    if not isinstance(value, list) or not all(isinstance(n, str) and n for n in value):
        raise ValueError(f"{where}: expected a list of objectNames")
    return tuple(value)


def _source(source, where="ribbon.yaml"):
    """A source of ribbon.yaml as a TABS source."""
    if not isinstance(source, dict):
        raise ValueError(f"{where}: a source is a mapping (toolbar:, main: or menu:)")
    if "toolbar" in source:
        if not isinstance(source["toolbar"], str) or not source["toolbar"]:
            raise ValueError(f"{where}: toolbar: expected a toolbar objectName")
        actions = source.get("actions")
        return source["toolbar"], None if actions is None else _names(actions, f"{where}: actions")
    if "main" in source:
        return "@", _names(source["main"], f"{where}: main")
    if "menu" in source:
        return "menu", _names(source["menu"], f"{where}: menu")
    if "dropdown" in source:
        return DROPDOWN, _dropdown(source["dropdown"], where)
    for kind in LABEL_KINDS:
        if kind in source:
            return kind, _label(kind, source[kind], where)[1:]
    raise ValueError(f"{where}: unknown source {source!r}")


def _dropdown(spec, where):
    """A dropdown of ribbon.yaml as (action objectName or None, title or
    None, item names; SEPARATOR for a line between items)."""
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: dropdown: expected action:, title: and items:")
    action, title = spec.get("action"), spec.get("title")
    for key, value in (("action", action), ("title", title)):
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError(f"{where}: dropdown: {key}: expected text")
    if action is None and title is None:
        raise ValueError(f"{where}: a dropdown needs an action: or a title:")
    where = f"{where}: dropdown {title or action!r}: items"
    items = spec.get("items") or []
    if not isinstance(items, list):
        raise ValueError(f"{where}: expected a list")
    parsed = []
    for item in items:
        if isinstance(item, str) and item:
            parsed.append(item)
        elif isinstance(item, dict) and len(item) == 1 and next(iter(item)) in LABEL_KINDS:
            kind = next(iter(item))
            parsed.append(_label(kind, item[kind], where))
        else:
            raise ValueError(f"{where}: expected objectNames, \"-\", caption: or note:, not {item!r}")
    return action, title, tuple(parsed)


def _group(group, where="ribbon.yaml"):
    """A group of ribbon.yaml as a TABS group."""
    if not isinstance(group, dict) or not isinstance(group.get("title"), str) or not group["title"]:
        raise ValueError(f"{where}: every group needs a title")
    where = f"{where}, group {group['title']!r}"
    layout = group.get("layout", LABELS)
    if layout not in LAYOUTS:
        raise ValueError(f"{where}: unknown layout {layout!r} (labels, icons or auto)")
    sources = group.get("sources") or []
    if not isinstance(sources, list):
        raise ValueError(f"{where}: sources: expected a list")
    item = (group["title"], tuple(_source(s, where) for s in sources),
            _names(group.get("large") or [], f"{where}: large"), layout)
    rows = group.get("rows")
    if rows and (not isinstance(rows, list) or not all(isinstance(r, list) for r in rows)):
        raise ValueError(f"{where}: rows: expected a list of lists of objectNames")
    return item + (tuple(_names(row, f"{where}: rows") for row in rows),) if rows else item


def parse_tabs(data):
    """The tabs of ribbon.yaml's parsed `data` as ((title, groups), ...);
    ValueError, in plain words, for anything the ribbon cannot show."""
    if not isinstance(data, dict) or not isinstance(data.get("tabs"), list) or not data["tabs"]:
        raise ValueError("ribbon.yaml: expected tabs: with a list of tabs")
    tabs = []
    for tab in data["tabs"]:
        if not isinstance(tab, dict) or not isinstance(tab.get("title"), str) or not tab["title"]:
            raise ValueError("ribbon.yaml: every tab needs a title")
        groups = tab.get("groups") or []
        if not isinstance(groups, list):
            raise ValueError(f"ribbon.yaml, tab {tab['title']!r}: groups: expected a list")
        tabs.append((tab["title"], tuple(_group(g, f"tab {tab['title']!r}") for g in groups)))
    titles = [title for title, _groups in tabs]
    twice = sorted({title for title in titles if titles.count(title) > 1})
    if twice:
        raise ValueError(f"ribbon.yaml: tab titles must differ: {', '.join(twice)}")
    if PLUGIN_TAB not in titles:
        raise ValueError(f"ribbon.yaml: a tab titled {PLUGIN_TAB!r} is needed (plugins' toolbars go there)")
    parse_labels(data)
    return tuple(tabs)


def parse_labels(data):
    """ribbon.yaml's labels: {objectName: text} — the texts of buttons
    given one of one's own, wherever they are ({title} in it: the label the
    ribbon would give it, {id}: its objectName)."""
    labels = data.get("labels") or {}
    if not isinstance(labels, dict) or not all(
            isinstance(k, str) and k and isinstance(v, str) for k, v in labels.items()):
        raise ValueError("ribbon.yaml: labels: expected objectName: \"text\" pairs")
    return dict(labels)


def read_tabs_text(text):
    """parse_tabs of ribbon.yaml's `text`."""
    return parse_tabs(yaml.safe_load(text))


def load_tabs(path=TABS_FILE):
    """The tabs of ribbon.yaml at `path` as ((title, groups), ...)."""
    with open(path, encoding="utf-8") as stream:
        return read_tabs_text(stream.read())


def _startup_tabs():
    """(tabs, file read, why the profile's file was not read or None);
    LABEL_OVERRIDES from the same file."""
    global LABEL_OVERRIDES  # pylint: disable=global-statement
    try:
        path = user_tabs_file()
    except (ImportError, RuntimeError):
        path = None
    if path and os.path.exists(path):
        try:
            tabs = load_tabs(path)
            with open(path, encoding="utf-8") as stream:
                LABEL_OVERRIDES = parse_labels(yaml.safe_load(stream))
            return tabs, path, None
        except (OSError, ValueError, yaml.YAMLError) as error:
            try:
                from qgis.core import Qgis, QgsMessageLog  # pylint: disable=import-outside-toplevel
                QgsMessageLog.logMessage(
                    f"{path} could not be read, the default ribbon is shown: {error}", "QGIS Studio Themes",
                    Qgis.MessageLevel.Warning)
            except (ImportError, RuntimeError):
                pass
            LABEL_OVERRIDES = {}
            return load_tabs(), TABS_FILE, f"{error}"
    return load_tabs(), TABS_FILE, None


# Buttons' texts of one's own (ribbon.yaml labels:), by objectName.
LABEL_OVERRIDES = {}


# The tabs shown, the file they came from and the profile file's error.
TABS, TABS_SOURCE, TABS_ERROR = _startup_tabs()
# The tab shown when none was chosen yet.
DEFAULT_TAB = "Home"
# Milliseconds before the tab shown is saved, after the last click.
TAB_SAVE_DELAY = 1000
# The pages not shown are built after startup (PREBUILD_DELAY ms), one
# every PREBUILD_STEP ms, so the first click on a tab needs no building.
PREBUILD_DELAY = 4000
PREBUILD_STEP = 60
# Menu items the ribbon leaves out: View > Toolbars (the ribbon stands for
# the toolbars) and submenus whose commands QGIS's tool buttons on the
# ribbon already offer (Measure, Select...).
SKIPPED_MENU_ITEMS = (
    "mToolbarMenu", "menuData_Filtering", "mMenuMeasure", "mMenuSelect", "mMenuEditAttributes", "m3DMapViewsMenu",
    "mMenuElevationProfiles", "menuImport_Export",
    # Web > MetaSearch: its button is on the Web toolbar, its help in Help >
    # Plugins.
    "MetaSearch",
)
# Icons for commands QGIS gives none (studio_icons ICON_MAP names), by
# action or menu objectName; GENERIC_MENU_ICON for other icon-less menus.
ICON_FALLBACKS = {
    "mActionCloseProject": "ribbon/close.svg", "mActionExit": "ribbon/exit.svg",
    "mActionRevertProject": "ribbon/revert.svg", "mActionSnappingOptions": "ribbon/snapping.svg",
    "mActionReselect": "ribbon/reselect.svg",
    "mActionDxfExport": "ribbon/export.svg", "mActionDwgImport": "ribbon/import.svg",
    "mProjectFromTemplateMenu": "ribbon/template.svg", "mRecentProjectsMenu": "ribbon/recent.svg",
    "mProjectFromStorageMenu": "ribbon/open-from.svg", "mProjectToStorageMenu": "ribbon/save-to.svg",
    "mLayoutsMenu": "ribbon/layouts.svg", "mMenuProjectModels": "ribbon/models.svg",
    "mMenuPasteAs": "ribbon/paste-as.svg", "mMenuAnnotation": "ribbon/annotation.svg",
    "mActionManage3DMapViews": "ribbon/manage.svg", "mActionManageElevationProfiles": "ribbon/manage.svg",
    "mMenuDecorations": "ribbon/decorations.svg", "mMenuPreviewMode": "ribbon/preview.svg",
    "mMenuLayerVisibility": "ribbon/preview.svg", "mPanelMenu": "ribbon/panels.svg",
    "mActionToggleFullScreen": "ribbon/full-screen.svg", "mActionTogglePanelsVisibility": "ribbon/panels.svg",
    "mActionToggleMapOnly": "ribbon/map-only.svg",
    "mAddLayerMenu": "ribbon/add-layer.svg", "mNewLayerMenu": "ribbon/create-layer.svg",
    "mActionEmbedLayers": "ribbon/embed.svg", "mActionAddLayerDefinition": "ribbon/layer-definition.svg",
    "mMenuFilterTable": "ribbon/filter.svg", "mActionLayerSaveAs": "ribbon/export.svg",
    "mActionSaveLayerDefinition": "ribbon/layer-definition.svg", "mActionSetLayerScaleVisibility": "ribbon/preview.svg",
    "mActionSetLayerCRS": "ribbon/crs.svg", "mActionSetProjectCRSFromLayer": "ribbon/project-crs.svg",
    "mActionLayerProperties": "ribbon/properties.svg", "mActionLayerSubsetString": "ribbon/filter.svg",
    "mUserProfileMenu": "ribbon/profiles.svg", "mActionShowMeshCalculator": "ribbon/calculator.svg",
    "mActionHelpAPI": "ribbon/docs.svg", "mActionHelpPyQgisAPI": "ribbon/docs.svg", "mMenuPluginHelp": "ribbon/docs.svg",
    "mActionReportaBug": "ribbon/bug.svg", "mActionDonate": "ribbon/donate.svg",
    "mActionGetInvolved": "ribbon/community.svg", "mActionNeedSupport": "ribbon/support.svg",
    "MetaSearch": "ribbon/web.svg",
}
GENERIC_MENU_ICON = "ribbon/tools.svg"
# The toolbar whose actions are the buttons right of the tabs (other
# toolbars, plugins', get a group on PLUGIN_TAB).
CORNER_TOOLBAR = "mHelpToolBar"

# Shorter labels than the actions' own (tooltips keep the full text), by
# objectName; for QGIS's tool buttons, the group's name for whichever tool
# is chosen.
LABELS_BY_NAME = {
    "mActionNewProject": "New", "mActionOpenProject": "Open", "mActionSaveProject": "Save",
    "mActionNewPrintLayout": "New Layout", "mActionShowLayoutManager": "Layouts",
    "mActionStyleManager": "Style Manager",
    "ActionSelect": "Select", "ActionDeselection": "Deselect", "mActionReselect": "Reselect",
    "mActionZoomIn": "Zoom In", "mActionZoomOut": "Zoom Out", "mActionZoomFullExtent": "Full Extent",
    "mActionIdentify": "Identify", "ActionOpenTable": "Attribute Table", "mActionOpenFieldCalc": "Field Calculator",
    "mActionStatisticalSummary": "Statistics", "mActionShowProcessingToolbox": "Toolbox",
    "ActionMeasure": "Measure", "mActionMapTips": "Map Tips", "ActionFeatureAction": "Actions",
    "mActionDataSourceManager": "Data Source Manager",
    "mActionAddOgrLayer": "Vector", "mActionAddRasterLayer": "Raster", "mActionAddMeshLayer": "Mesh",
    "mActionAddDelimitedText": "Delimited Text", "mActionAddSpatiaLiteLayer": "SpatiaLite",
    "mActionAddVirtualLayer": "Virtual", "ActionAddDbLayer": "Database", "mActionAddWmsLayer": "WMS/WMTS",
    "mActionAddWcsLayer": "WCS", "mActionAddWfsLayer": "WFS", "mActionAddStacLayer": "STAC",
    "ActionNewLayer": "Other Layer",
    "mActionNewGeoPackageLayer": "GeoPackage Layer", "mActionNewVectorLayer": "Shapefile",
    "mActionNewSpatiaLiteLayer": "SpatiaLite", "mActionNewMemoryLayer": "Scratch Layer",
    "mActionNewMeshLayer": "Mesh Layer", "mActionNewVirtualLayer": "Virtual Layer",
    "mActionToggleEditing": "Toggle Editing", "mActionSaveLayerEdits": "Save Edits", "mActionAllEdits": "All Edits",
    "mActionAddFeature": "Add Feature", "ActionVertexTool": "Vertex Tool", "mDigitizeModeToolButton": "Digitize Mode",
    "mActionMultiEditAttributes": "Edit Attributes", "mActionDeleteSelected": "Delete",
    "mActionCutFeatures": "Cut", "mActionCopyFeatures": "Copy", "mActionPasteFeatures": "Paste",
    "mActionUndo": "Undo", "mActionRedo": "Redo",
    "mEnableAction": "Advanced Digitizing",
    "ActionMoveFeatureTool": "Move", "mActionRotateFeature": "Rotate", "mActionScaleFeature": "Scale",
    "mActionSimplifyFeature": "Simplify", "mActionOffsetCurve": "Offset Curve", "mActionReverseLine": "Reverse Line",
    "mActionAddRing": "Add Ring", "mActionAddPart": "Add Part", "mActionFillRing": "Fill Ring",
    "mActionDeleteRing": "Delete Ring", "mActionDeletePart": "Delete Part",
    "mActionReshapeFeatures": "Reshape", "mActionChamferFillet": "Chamfer/Fillet",
    "mActionTrimExtendFeature": "Trim/Extend", "mActionSplitFeatures": "Split Features",
    "mActionSplitParts": "Split Parts", "mActionMergeFeatures": "Merge Features",
    "mActionMergeFeatureAttributes": "Merge Attributes", "ActionPointSymbolTools": "Point Symbols",
    "mActionLabeling": "Labels", "mActionDiagramProperties": "Diagrams",
    "mActionShowPinnedLabels": "Pinned Labels", "mActionShowUnplacedLabels": "Unplaced Labels",
    "mActionPinLabels": "Pin/Unpin", "mActionShowHideLabels": "Show/Hide", "mActionMoveLabel": "Move",
    "mActionRotateLabel": "Rotate", "mActionChangeLabelProperties": "Properties",
    "annotationLayerToolButtonAction": "Annotation Layer", "mActionSelectAnnotation": "Select",
    "mActionModifyAnnotation": "Edit Nodes", "ActionAnnotation": "Map Annotations",
    "mActionNewMapCanvas": "New Map View", "mActionNew3DMapCanvas": "New 3D Map View",
    "mActionNewBookmark": "New Bookmark", "mActionShowBookmarks": "Bookmarks",
    "mActionTemporalController": "Temporal Controller",
    "mActionShowRasterCalculator": "Raster Calculator", "mActionShowGeoreferencer": "Georeferencer",
    "mActionShowMeshCalculator": "Mesh Calculator",
    "mConnectAction": "Connect", "mRecenterAction": "Recenter",
    "mDestinationLayerButtonAction": "Destination Layer", "mAddTrackVertexAction": "Add Vertex",
    "mCreateFeatureAction": "Create Feature", "mResetFeatureAction": "Reset Track",
    "mShowInfoAction": "Information", "mSettingsMenuAction": "Settings",
    "mActionShowPythonDialog": "Python Console",
    # Menu commands and menus (by the menu's objectName).
    "mActionSaveProjectAs": "Save As", "mActionRevertProject": "Revert", "mActionCloseProject": "Close",
    "mActionExit": "Exit QGIS", "mProjectFromTemplateMenu": "From Template", "mRecentProjectsMenu": "Recent",
    "mProjectFromStorageMenu": "Open From", "mProjectToStorageMenu": "Save To",
    "mActionProjectProperties": "Properties", "mActionSnappingOptions": "Snapping Options",
    "mActionSaveMapAsImage": "Export Image", "mActionSaveMapAsPdf": "Export PDF", "mActionDxfExport": "Export DXF",
    "mActionDwgImport": "Import DWG/DXF", "mActionNewReport": "New Report", "mLayoutsMenu": "Open Layout",
    "mMenuProjectModels": "Project Models", "mMenuPasteAs": "Paste As",
    "mActionNew3DMapCanvasGlobe": "New 3D Globe", "mActionManage3DMapViews": "Manage 3D Views",
    "mActionShowBookmarkManager": "Bookmark Manager", "mActionElevationProfile": "Elevation Profile",
    "mActionManageElevationProfiles": "Manage Profiles", "mActionElevationController": "Elevation Controller",
    "mMenuDecorations": "Decorations", "mMenuPreviewMode": "Preview Mode", "mMenuLayerVisibility": "Layer Visibility",
    "mPanelMenu": "Panels", "mActionToggleFullScreen": "Full Screen", "mActionTogglePanelsVisibility": "Hide Panels",
    "mActionToggleMapOnly": "Map Only",
    "mAddLayerMenu": "All Layer Types", "mNewLayerMenu": "All New Layers", "mActionEmbedLayers": "Embed Layers",
    "mActionAddLayerDefinition": "Layer Definition", "mActionLayerProperties": "Layer Properties",
    "mActionLayerSubsetString": "Filter", "mActionDuplicateLayer": "Duplicate", "mActionSetLayerCRS": "Set Layer CRS",
    "mActionSetProjectCRSFromLayer": "Set Project CRS", "mActionSetLayerScaleVisibility": "Scale Visibility",
    "mActionLayerSaveAs": "Save As", "mActionSaveLayerDefinition": "Save as Definition",
    "mActionRemoveLayer": "Remove", "mActionCopyStyle": "Copy Style", "mActionPasteStyle": "Paste Style",
    "mActionCopyLayer": "Copy Layer", "mActionPasteLayer": "Paste Layer",
    "mActionAddToOverview": "Show in Overview", "mActionAddAllToOverview": "Show All",
    "mActionRemoveAllFromOverview": "Hide All", "mActionReindexMesh": "Reindex",
    "toolboxAction": "Processing", "modelerAction": "Model Designer", "historyAction": "History",
    "resultsViewer": "Results Viewer", "editInPlaceFeatures": "Edit In-Place", "optionsAction": "Options",
    "mActionManagePlugins": "Manage Plugins", "dbManager": "DB Manager", "mActionQueryHistory": "Query History",
    "mActionOptions": "Options", "mActionConfigureShortcuts": "Shortcuts", "mActionCustomization": "Customization",
    "mActionCustomProjection": "Custom CRS", "mUserProfileMenu": "User Profiles",
    "mActionHelpContents": "Help", "mActionHelpAPI": "C++ API", "mActionHelpPyQgisAPI": "PyQGIS API",
    "mMenuPluginHelp": "Plugin Help", "mActionQgisHomePage": "Home Page", "mActionCheckQgisVersion": "Check Version",
    "mActionAbout": "About", "mActionReportaBug": "Report Issue", "mActionGetInvolved": "Get Involved",
    "mActionNeedSupport": "Support", "mActionDonate": "Donate", "mActionSponsors": "Sponsors",
}
# Widgets QGIS puts on toolbars that the ribbon leaves out: the snapping
# widget's own container (its buttons and fields are on the ribbon).
SKIPPED_WIDGETS = ("QgsSnappingWidget",)


def label_for(key, own, override=True):
    """The label of the command named `key` (see _key): its short one
    (LABELS_BY_NAME) in QGIS's language (studio_i18n), else `own`, its own
    text, which QGIS translates; or the text ribbon.yaml's labels: give it
    ({title} in it: that label, {id}: `key`)."""
    label = translated_label(LABELS_BY_NAME.get(key)) or own
    if override and key in LABEL_OVERRIDES:
        return label_text(LABEL_OVERRIDES[key], label, key)
    return label


def clean(text):
    """An action's text as a label: no mnemonic, ellipsis or markup."""
    text = re.sub(r"<[^>]+>", "", (text or "").replace("&&", "\0").replace("&", "").replace("\0", "&"))
    return text.replace("…", "").replace("...", "").strip()


def two_lines(text):
    """A large button's label on at most two lines, broken at the space
    nearest the middle."""
    if len(text) <= 9 or " " not in text:
        return text
    middle = len(text) / 2
    spaces = [i for i, char in enumerate(text) if char == " "]
    cut = min(spaces, key=lambda i: abs(i - middle))
    return text[:cut] + "\n" + text[cut + 1:]


def _uses_widget_actions(menu):
    return menu is not None and any(isinstance(a, QWidgetAction) for a in menu.actions())


def _key(action):
    """An action's name in TABS and the tables above: its objectName, or for
    a menu's own action (which has none) the menu's."""
    if action.objectName():
        return action.objectName()
    menu = menu_of(action)
    return menu.objectName() if menu is not None else ""


class _GapEngine(QIconEngine):
    """An icon with an empty strip right of it (`under` False) or under it,
    so Qt leaves that much more room between a button's icon and label."""

    def __init__(self, icon, under):
        super().__init__()
        self.icon = icon
        self.under = under

    def paint(self, painter, rect, mode, state):
        side = rect.width() if self.under else rect.height()
        self.icon.paint(painter, QRect(rect.x(), rect.y(), side, side),
                        Qt.AlignmentFlag.AlignCenter, mode, state)

    def pixmap(self, size, mode, state):
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap

    def clone(self):
        return _GapEngine(self.icon, self.under)


class _Button(QToolButton):
    """A ribbon button. With a fixed `label`, it keeps it when its action
    changes (QToolButton takes the action's text again on every change)."""

    def __init__(self, kind, label="", parent=None):
        super().__init__(parent)
        self._label = label
        self._placeholder = None
        self.setProperty("studioRibbon", kind)
        # Compact rows are 2 px lower: less padding (style.qss). Set before
        # the stylesheet first polishes the button.
        if DENSITY == "compact":
            self.setProperty("studioDensity", "compact")
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def actionEvent(self, event):  # pylint: disable=invalid-name
        super().actionEvent(event)
        if event.type() != QEvent.Type.ActionChanged:
            return
        if self._label and self.text() != self._label:
            self.setText(self._label)
        if self._placeholder is not None and self.icon().isNull():
            self.setIcon(self._placeholder)
        self._gap_icon()

    def _gap_icon(self):
        """Keep ICON_GAP between icon and label (see _GapEngine)."""
        kind = self.property("studioRibbon")
        icon = self.icon()
        if kind not in ("large", "small") or icon.isNull():
            return
        if icon.cacheKey() == getattr(self, "_gapped", None):
            return
        gapped = QIcon(_GapEngine(icon, kind == "large"))
        self._gapped = gapped.cacheKey()
        self.setIcon(gapped)

    def set_placeholder(self, size):
        """An empty icon for an action without one, so its label lines up
        with its neighbours'."""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        self._placeholder = QIcon(pixmap)
        self.setIcon(self._placeholder)
        self._gap_icon()

    def set_label(self, label):
        self._label = label
        if label:
            self.setText(label)

    def follow(self, source):
        """As a clone of QGIS's tool button `source`: show the tool it holds
        whenever another is chosen, also on another tab's clone of it."""
        self._source = source
        source.triggered.connect(self.sync)

    def sync(self, *_args):
        source = getattr(self, "_source", None)
        if source is None or sip.isdeleted(source):
            return
        current = source.defaultAction()
        if current is None:
            return
        mine = self.defaultAction()
        if mine is None or sip.unwrapinstance(mine) != sip.unwrapinstance(current):
            self.setDefaultAction(current)
            self.set_label(self._label)
            self._gap_icon()


class _BorrowingMenu(QMenu):
    """A menu showing another menu's actions while it is open. A menu
    holding widgets (QWidgetAction: a spin box...) closes again at once when
    shown for a button other than its own, and a widget can only be in one
    menu: the actions move here while this one is open and go back when it
    closes."""

    def __init__(self, source, parent):
        super().__init__(parent)
        self._source = source
        self._borrowed = []
        self.aboutToShow.connect(self._borrow)
        self.aboutToHide.connect(lambda: QTimer.singleShot(0, self._give_back))

    def _borrow(self):
        if self._borrowed or sip.isdeleted(self._source):
            return
        self._borrowed = self._source.actions()
        for action in self._borrowed:
            self._source.removeAction(action)
        self.addActions(self._borrowed)

    def _give_back(self):
        if sip.isdeleted(self) or sip.isdeleted(self._source) or not self._borrowed:
            return
        for action in self._borrowed:
            self.removeAction(action)
        self._source.addActions(self._borrowed)
        self._borrowed = []


class _Tabs(QTabBar):
    """The ribbon's tabs: the current one's name underlined in the accent
    (the palette's Link colour), as wide as the name, which a stylesheet
    cannot size."""

    UNDERLINE = 2
    GAP = 3  # between the underline and the tab's bottom edge
    # Compact tabs: lower, so a pixel row stays clear between it and the
    # name (style.qss gives compact tabs a pixel more below the name), as
    # in standard tabs; at 2 it touched the name.
    COMPACT_GAP = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gap = self.GAP

    def paintEvent(self, event):  # pylint: disable=invalid-name
        super().paintEvent(event)
        index = self.currentIndex()
        # The first tab (Project) is a coloured button (style.qss): no
        # underline on it.
        if index <= 0:
            return
        tab = self.tabRect(index)
        width = self.fontMetrics().horizontalAdvance(self.tabText(index)) + 4
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(QPalette.ColorRole.Link))
        y = tab.bottom() + 1 - self.gap - self.UNDERLINE
        painter.drawRoundedRect(tab.center().x() + 1 - width // 2, y, width, self.UNDERLINE, 1, 1)
        painter.end()


class Ribbon(QWidget):
    """The tabs and the current page (see the module docstring). Pages
    are built by `build(index, page)` when first shown and after
    invalidate()."""

    def __init__(self, titles, build, corner, parent=None):
        super().__init__(parent)
        self.setObjectName("studioRibbon")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._build = build
        self._built = set()
        # A page's height (see page_height), set by the ribbon's owner.
        self.page_height = page_height(studio_toolbars.title_font())
        layout = QVBoxLayout(self)
        # Room under the page for the ribbon's bottom line (none when
        # collapsed: the tab row's line closes the ribbon off then).
        layout.setContentsMargins(0, 0, 0, 1)
        layout.setSpacing(0)
        # The tab row draws the line over the page; the current tab, a
        # child drawn after it, covers the line where it opens into the page.
        bar = QWidget()
        bar.setObjectName("studioRibbonBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._top = top = QHBoxLayout(bar)
        # Room above the tabs: the ribbon is the window's top row.
        top.setContentsMargins(6, BAR_TOP, 6, 0)
        top.setSpacing(2)
        self.tabs = _Tabs()
        self.tabs.setObjectName("studioRibbonTabs")
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for title in titles:
            self.tabs.addTab(title)
        top.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignBottom)
        top.addStretch(1)
        # Help and collapse centred on the tabs' names, which sit below
        # the row's middle (the tabs' top margin).
        self._buttons = buttons = QHBoxLayout()
        buttons.setContentsMargins(0, TAB_TOP, 0, 0)
        buttons.setSpacing(2)
        buttons.addWidget(corner)
        self.collapse = QToolButton()
        self.collapse.setObjectName("studioRibbonCollapse")
        self.collapse.setAutoRaise(True)
        self.collapse.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.collapse.setCheckable(True)
        self.collapse.setToolTip(tr("Collapse the ribbon to its tabs (double-click a tab)"))
        self.collapse.toggled.connect(self.set_collapsed)
        buttons.addWidget(self.collapse)
        top.addLayout(buttons)
        layout.addWidget(bar)
        self.pages = QStackedWidget()
        self.pages.setObjectName("studioRibbonPages")
        for _title in titles:
            page = QScrollArea()
            page.setObjectName("studioRibbonPage")
            page.setFrameShape(QFrame.Shape.NoFrame)
            page.setWidgetResizable(True)
            # No scroll bar: the ribbon keeps one height (a change would lay
            # the whole window out again); the wheel scrolls a wide page.
            page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            page.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.pages.addWidget(page)
        layout.addWidget(self.pages)
        self.tabs.currentChanged.connect(self._show_page)
        self.tabs.tabBarDoubleClicked.connect(lambda _index: self.collapse.toggle())
        self.tabs.tabBarClicked.connect(self._tab_clicked)

    def show_tab(self, index):
        index = max(0, min(index, self.tabs.count() - 1))
        if self.tabs.currentIndex() != index:
            self.tabs.setCurrentIndex(index)
        else:
            self._show_page(index)

    def invalidate(self, index):
        """The page's toolbars changed: built again now if it shows, else
        when it is next shown."""
        self._built.discard(index)
        if index == self.tabs.currentIndex():
            self._show_page(index)

    def _show_page(self, index):
        if index < 0:
            return
        self._ensure_built(index)
        self.pages.setCurrentIndex(index)
        self._fit_height()

    def _ensure_built(self, index):
        if index not in self._built:
            self._built.add(index)
            page = self.pages.widget(index)
            old = page.takeWidget()
            page.setWidget(self._build(index, old))

    def prebuild_next(self):
        """Build one page not built yet (in idle time, so the first click
        on each tab shows it at once); False when every page is built."""
        for index in range(self.pages.count()):
            if index not in self._built:
                self._ensure_built(index)
                return True
        return False

    def _tab_clicked(self, _index):
        # Collapsed: a tab shows its page again.
        if self.collapse.isChecked():
            self.collapse.setChecked(False)

    def set_collapsed(self, collapsed):
        if self.collapse.isChecked() != collapsed:
            self.collapse.setChecked(collapsed)
            return
        self.collapse.setProperty("collapsed", "true" if collapsed else None)
        self.collapse.style().unpolish(self.collapse)
        self.collapse.style().polish(self.collapse)
        # Collapsed, the current tab opens into no page: a plain tab, its
        # name still underlined (style.qss, [collapsed]).
        self.tabs.setProperty("collapsed", "true" if collapsed else None)
        self.tabs.style().unpolish(self.tabs)
        self.tabs.style().polish(self.tabs)
        self.layout().setContentsMargins(0, 0, 0, 0 if collapsed else 1)
        self.pages.setVisible(not collapsed)
        self._fit_height()

    def set_density(self, density):
        """Tabs in `density` (DENSITIES): compact ones have less padding
        (style.qss, [density=\"compact\"]) and less room above them."""
        compact = density == "compact"
        value = "compact" if compact else None
        if self.tabs.property("density") == value:
            return
        self._top.setContentsMargins(6, COMPACT_BAR_TOP if compact else BAR_TOP, 6, 0)
        self._buttons.setContentsMargins(0, COMPACT_TAB_TOP if compact else TAB_TOP, 0, 0)
        self.tabs.gap = _Tabs.COMPACT_GAP if compact else _Tabs.GAP
        for widget in (self.tabs, self.collapse):
            widget.setProperty("density", value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            # A tab bar keeps its tabs' sizes until its style changes.
            QApplication.sendEvent(widget, QEvent(QEvent.Type.StyleChange))
        # Compact tabs' names at most COMPACT_TAB_FONT px (the UI font's
        # otherwise, as before).
        self.tabs.setFont(QFont())
        if compact:
            font = QFont(self.tabs.font())
            if QFontInfo(font).pixelSize() > COMPACT_TAB_FONT:
                font.setPixelSize(COMPACT_TAB_FONT)
                self.tabs.setFont(font)
        self.tabs.update()

    def wheelEvent(self, event):  # pylint: disable=invalid-name
        """The wheel scrolls a page wider than the window sideways."""
        page = self.pages.currentWidget()
        bar = page.horizontalScrollBar() if page is not None else None
        if bar is None or bar.maximum() <= 0:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y() or event.angleDelta().x()
        bar.setValue(bar.value() - delta)
        event.accept()

    def fit_height(self):
        """Take a new page_height at once."""
        self._fit_height()

    def _fit_height(self):
        """The pages' one height (see page_height)."""
        if self.pages.height() != self.page_height or self.pages.minimumHeight() != self.page_height:
            self.pages.setFixedHeight(self.page_height)


def set_menu_bar_folded(window, folded):
    """The menu bar folded away while the ribbon shows (its commands are on
    the ribbon's tabs): no height and no line (style.qss,
    QMenuBar[studioRibbon]). Not hidden: Alt with a menu's letter (Alt+P
    for Project...) opens it only from a visible menu bar."""
    menu_bar = window.menuBar()
    if menu_bar is None or bool(menu_bar.property("studioRibbon")) == folded:
        return
    menu_bar.setProperty("studioRibbon", True if folded else None)
    menu_bar.style().unpolish(menu_bar)
    menu_bar.style().polish(menu_bar)
    # After polishing, which restores the size limits a stylesheet saw.
    menu_bar.setMaximumHeight(0 if folded else QWIDGETSIZE_MAX)


def page_height(caption_font, position="bottom"):
    """A page's height: a group's buttons and margins, and its name's line
    when the name goes above or below them (a name left of the buttons, or
    none, takes no height)."""
    caption = SPACING + QFontMetrics(caption_font).height() if position in ("top", "bottom") else 0
    return GROUP_MARGINS[1] + BODY + caption + GROUP_MARGINS[3]


class _Caption(QLabel):
    """A group's name: across, or reading upwards left of the buttons
    (`upright`: a column as wide as a line of text, at the group's left
    edge), in the stylesheet's caption colour (QLabel#studioRibbonCaption)."""

    def __init__(self, text, upright, font, parent=None):
        super().__init__(text, parent)
        self.setObjectName("studioRibbonCaption")
        self.setFont(font)
        self._upright = upright
        if upright:
            metrics = QFontMetrics(font)
            self._upright_size = QSize(metrics.height(), metrics.horizontalAdvance(text) + 2)
            self.setFixedWidth(self._upright_size.width())

    def sizeHint(self):  # pylint: disable=invalid-name
        return self._upright_size if self._upright else super().sizeHint()

    def minimumSizeHint(self):  # pylint: disable=invalid-name
        return self._upright_size if self._upright else super().minimumSizeHint()

    def paintEvent(self, event):  # pylint: disable=invalid-name
        if not self._upright:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.translate(0, self.height())
        painter.rotate(-90)
        painter.drawText(QRect(0, 0, self.height(), self.width()), Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()


class StudioRibbon(QObject):
    """Shows the ribbon in place of the main window's toolbars and keeps it
    up to date (see the module docstring)."""

    WINDOW_EVENTS = (QEvent.Type.ChildPolished,)
    MENU_BAR_EVENTS = (QEvent.Type.StyleChange, QEvent.Type.ActionAdded, QEvent.Type.ActionRemoved)
    MENU_EVENTS = (QEvent.Type.ActionAdded, QEvent.Type.ActionRemoved)
    TOOLBAR_EVENTS = (QEvent.Type.ActionAdded, QEvent.Type.ActionRemoved, QEvent.Type.ActionChanged)

    def __init__(self, iface, hub, icons=None):
        super().__init__()
        self._iface = iface
        self._hub = hub
        # The plugin's IconSwapper: the theme's icons for the commands
        # placed (swap_action), also those QGIS gives none (adopt); the
        # actions given one.
        self._icons = icons
        self._adopted = []
        self._window = None
        self._host = None
        self._ribbon = None
        # The tab shown, saved when the tabs rest (see _tab_changed).
        self._tab = None
        self._tab_timer = QTimer(self)
        self._tab_timer.setSingleShot(True)
        self._tab_timer.setInterval(TAB_SAVE_DELAY)
        self._tab_timer.timeout.connect(self._save_tab)
        # Toolbars hidden for the ribbon (by objectName, so they survive a
        # session), toolbars watched, and the tab index of each toolbar's
        # groups (QGIS's own; others are on PLUGIN_TAB).
        self._hidden = []
        self._watched = []
        self._tab_of = {}
        # The tab indexes of each menu whose items a group shows ("menu"
        # sources), the menus watched, and every name TABS places itself.
        self._menu_tabs = {}
        self._menus = {}
        self._placed_names = set()
        # Names dropdowns hold (their own command and their items): not
        # among a toolbar's other buttons, nor in a menu's "More" group.
        self._dropdown_names = set()
        for index, (_title, groups) in enumerate(TABS):
            for group in groups:
                for source, names in group[1]:
                    if source == "menu":
                        for name in names:
                            self._menu_tabs.setdefault(name, set()).add(index)
                        continue
                    if source in LABEL_KINDS:
                        continue
                    if source == DROPDOWN:
                        held = {item_menu(n) or n for n in (names[0],) + names[2]
                                if isinstance(n, str) and n != SEPARATOR}
                        self._dropdown_names |= held
                        self._placed_names |= held
                        continue
                    self._placed_names.update(names or ())
                    if source != "@":
                        self._tab_of.setdefault(source, set()).add(index)
        # Actions named in TABS, per toolbar: a group listing none takes
        # the others.
        self._named = {}
        for _title, groups in TABS:
            for group in groups:
                for toolbar, names in group[1]:
                    if toolbar not in ("@", "menu", DROPDOWN) + LABEL_KINDS:
                        self._named.setdefault(toolbar, set()).update(names or ())
        # Names already on the ribbon while a page is built (see _covered).
        self._covered = set()
        # The dropdowns' own actions (their menus filled when opened), by
        # spec, and the spec of each, by C++ object.
        self._dropdowns = {}
        self._dropdown_of = {}
        # Captions' and notes' stand-in actions, by (kind, text, for), and
        # the spec of each, by C++ object.
        self._labels = {}
        self._label_of = {}
        # Widgets borrowed from toolbars: [(widget, toolbar, action)].
        self._borrowed = []
        # Action visibility as last seen, by C++ object (ActionChanged is
        # frequent; only a visibility change changes a page). Python ids
        # are no keys: QGIS's objects get a new wrapper on each access.
        self._visible = {}
        self._dirty = set()
        # The actions on the ribbon (by C++ object), as last built.
        self.placed = set()
        self._caption_font = studio_toolbars.title_font()
        # The groups' names: where they go and which name shows (see
        # set_style); the short names given on the page being built.
        self._caption_position = CAPTION_POSITION
        self._caption_names = CAPTION_NAMES
        self._shorts_taken = set()
        # The ribbon's size and density settings (RIBBON_SIZES, DENSITIES).
        self._size_choice = "auto"
        self._density = DEFAULT_DENSITY
        self._corner = None

    @property
    def active(self):
        return self._ribbon is not None

    def refresh_icons(self):
        """The icon style changed: the icons given for the ribbon go, and
        every page is built again (giving them in the new style)."""
        for action in self._adopted:
            if not sip.isdeleted(action):
                action.setIcon(QIcon())
        self._adopted = []
        if self._ribbon is not None:
            for index in range(self._ribbon.tabs.count()):
                self._ribbon.invalidate(index)

    def set_style(self, position, names, size, weight, ribbon_size="auto", density=DEFAULT_DENSITY):
        """The groups' names (where they go, which name shows, their font:
        studio_toolbars.POSITIONS, NAME_STYLES, TITLE_SIZES, WEIGHTS) and
        the ribbon's size and density (RIBBON_SIZES, DENSITIES), as set in
        the settings dialog. Pages are built again when any changed."""
        position = position if position in studio_toolbars.POSITIONS else CAPTION_POSITION
        names = names if names in studio_toolbars.NAME_STYLES else CAPTION_NAMES
        font = studio_toolbars.title_font(size, weight)
        ribbon_size = ribbon_size if ribbon_size in RIBBON_SIZES else "auto"
        density = density if density in DENSITIES else DEFAULT_DENSITY
        changed = (font, position, names) != (self._caption_font, self._caption_position, self._caption_names)
        self._caption_font, self._caption_position, self._caption_names = font, position, names
        self._size_choice, self._density = ribbon_size, density
        if self._ribbon is not None:
            self._apply_sizes(force=changed)

    def _toolbar_size(self):
        """The toolbar icon size the ribbon's sizes stand for: its own size
        setting, or QGIS's toolbar icon size."""
        fixed = RIBBON_SIZES.get(self._size_choice)
        if fixed is not None:
            return fixed
        window = self._window
        return window.iconSize().width() if window is not None and not sip.isdeleted(window) else 24

    @staticmethod
    def _label_height():
        """The height of a large button's two-line label: in the font the
        stylesheet gives ribbon buttons (QGIS's font size setting)."""
        probe = QToolButton()
        probe.setProperty("studioRibbon", "large")
        probe.ensurePolished()
        height = 2 * probe.fontMetrics().height()
        probe.deleteLater()
        return height

    def _apply_sizes(self, force=False):
        """Use the sizes and density set (set_sizes); every page is built
        again when they changed (or `force`)."""
        changed = set_sizes(self._toolbar_size(), self._density, self._label_height())
        if self._ribbon is None:
            return
        self._ribbon.set_density(self._density)
        if changed or force:
            self._ribbon.page_height = page_height(self._caption_font, self._caption_position)
            self._ribbon.fit_height()
            if changed:
                self._fill_corner()  # Help's buttons, in the new row height
            for index in range(self._ribbon.tabs.count()):
                self._ribbon.invalidate(index)

    def _icon_size_changed(self, *_args):
        """QGIS's toolbar icon size changed: the buttons and rows follow
        (unless the ribbon has a size of its own) and every page is built
        again in the new sizes."""
        window = self._window
        if self._ribbon is None or window is None or sip.isdeleted(window):
            return
        self._apply_sizes()

    # ---- Showing and hiding -----------------------------------------------

    def activate(self):
        if self._ribbon is not None:
            return
        window = self._iface.mainWindow()
        self._window = window
        # Buttons in the sizes of QGIS's toolbar icon size (followed live)
        # or the ribbon's own size, in the density set.
        set_sizes(self._toolbar_size(), self._density, self._label_height())
        window.iconSizeChanged.connect(self._icon_size_changed)
        self._hidden = []
        hidden_before = QgsSettings().value(HIDDEN_SETTING, [], type=list) or []
        for toolbar in self._toolbars():
            if toolbar.isVisible() or toolbar.objectName() in hidden_before:
                self._hidden.append(toolbar.objectName())
            toolbar.hide()
        QgsSettings().setValue(HIDDEN_SETTING, self._hidden)
        for toolbar in self._toolbars():
            self._watch(toolbar)
        self._hub.watch(window, self, self.WINDOW_EVENTS, self._window_event)
        self._corner = QWidget()
        self._corner.setObjectName("studioRibbonCorner")
        corner_layout = QHBoxLayout(self._corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(2)
        self._watch_menus()
        self._ribbon = Ribbon([tr(title, "title") for title, _groups in TABS], self._build_page, self._corner)
        self._ribbon.set_density(self._density)
        self._ribbon.page_height = page_height(self._caption_font, self._caption_position)
        self._fill_corner()
        host = self._host = QToolBar(tr("Ribbon"), window)
        host.setObjectName(HOST_NAME)
        host.setMovable(False)
        host.setFloatable(False)
        host.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        host.toggleViewAction().setVisible(False)
        host.addWidget(self._ribbon)
        # No room around the ribbon: the layout took the margins of a
        # plain toolbar (style.qss QToolBar padding) before the host had
        # its name and rule (QToolBar#studioRibbonHost).
        host.layout().setContentsMargins(0, 0, 0, 0)
        host.layout().setSpacing(0)
        first = next((t for t in self._toolbars() if window.toolBarArea(t) == Qt.ToolBarArea.TopToolBarArea), None)
        if first is not None:
            window.insertToolBar(first, host)
            window.insertToolBarBreak(first)
        else:
            window.addToolBar(Qt.ToolBarArea.TopToolBarArea, host)
        host.show()
        set_menu_bar_folded(window, True)
        if window.menuBar() is not None:
            self._hub.watch(window.menuBar(), self, self.MENU_BAR_EVENTS, self._menu_bar_event)
        settings = QgsSettings()
        self._ribbon.set_collapsed(settings.value(COLLAPSED_SETTING, False, type=bool))
        # The tab by its title (before 1.2's last tabs: by its index).
        titles = [title for title, _groups in TABS]
        tab = settings.value(TAB_SETTING, DEFAULT_TAB, type=str)
        tab = tab if tab in titles else DEFAULT_TAB
        self._ribbon.show_tab(titles.index(tab) if tab in titles else 0)
        self._ribbon.tabs.currentChanged.connect(self._tab_changed)
        self._ribbon.collapse.toggled.connect(lambda collapsed: QgsSettings().setValue(COLLAPSED_SETTING, collapsed))
        QTimer.singleShot(PREBUILD_DELAY, self._prebuild)

    def _tab_changed(self, index):
        # Saved once the tabs rest: writing QGIS's settings costs a few
        # milliseconds, on every click while browsing the tabs.
        self._tab = TABS[index][0]
        self._tab_timer.start()

    def _save_tab(self):
        if self._tab is not None:
            QgsSettings().setValue(TAB_SETTING, self._tab)
            self._tab = None

    def _prebuild(self):
        """Build the pages not shown yet one by one, between events."""
        if self._ribbon is not None and self._ribbon.prebuild_next():
            QTimer.singleShot(PREBUILD_STEP, self._prebuild)

    def deactivate(self, forget=False):
        """Hide the ribbon and show the toolbars it hid. Only `forget` (the
        ribbon turned off in the settings) forgets which: on QGIS's exit the
        plugin is unloaded after QGIS saved the toolbars hidden, so the next
        session must know to show them again."""
        if self._ribbon is None:
            return
        self._tab_timer.stop()
        self._save_tab()
        window = self._window
        self._give_back()
        if not sip.isdeleted(window):
            try:
                window.iconSizeChanged.disconnect(self._icon_size_changed)
            except (TypeError, RuntimeError):
                pass
            self._hub.unwatch(window, self)
            if window.menuBar() is not None:
                self._hub.unwatch(window.menuBar(), self)
            set_menu_bar_folded(window, False)
        for toolbar in self._watched:
            if not sip.isdeleted(toolbar):
                self._hub.unwatch(toolbar, self)
        self._watched = []
        for menu in self._menus.values():
            if not sip.isdeleted(menu):
                self._hub.unwatch(menu, self)
        self._menus = {}
        for action in self._dropdowns.values():
            if not sip.isdeleted(action):
                menu = menu_of(action)
                if menu is not None:
                    menu.deleteLater()
                action.deleteLater()
        self._dropdowns = {}
        self._dropdown_of = {}
        for action in self._labels.values():
            if not sip.isdeleted(action):
                action.deleteLater()
        self._labels = {}
        self._label_of = {}
        # Icons given for the ribbon go: QGIS's menus show none there.
        for action in self._adopted:
            if not sip.isdeleted(action):
                action.setIcon(QIcon())
        self._adopted = []
        if self._host is not None and not sip.isdeleted(self._host):
            window.removeToolBar(self._host)
            self._host.hide()
            self._host.deleteLater()
        self._host = None
        self._ribbon = None
        self._corner = None
        hidden = set(self._hidden)
        for toolbar in self._toolbars():
            if toolbar.objectName() in hidden:
                toolbar.show()
        self._hidden = []
        self._visible = {}
        self._dirty = set()
        if forget:
            QgsSettings().remove(HIDDEN_SETTING)

    def _toolbars(self):
        """The main window's toolbars (its own children: a search of every
        widget below it would take far longer), not the ribbon's."""
        window = self._window or self._iface.mainWindow()
        return [t for t in window.findChildren(QToolBar, options=Qt.FindChildOption.FindDirectChildrenOnly)
                if t.objectName() != HOST_NAME]

    def _watch(self, toolbar):
        if toolbar in self._watched:
            return
        self._watched.append(toolbar)
        self._hub.watch(toolbar, self, self.TOOLBAR_EVENTS, self._toolbar_event)
        for action in toolbar.actions():
            self._visible[sip.unwrapinstance(action)] = action.isVisible()

    # ---- Changes ----------------------------------------------------------

    def _window_event(self, watched, event):
        """A toolbar added to the main window (a plugin's): hidden, and on
        the ribbon."""
        child = event.child()
        if (isinstance(child, QToolBar) and child.parent() is watched and child.objectName() != HOST_NAME
                and child not in self._watched):
            self._watch(child)
            if child.objectName() and child.objectName() not in self._hidden:
                self._hidden.append(child.objectName())
                QgsSettings().setValue(HIDDEN_SETTING, self._hidden)
            QTimer.singleShot(0, lambda toolbar=child: self._hide_new(toolbar))
            self._changed(child)

    def _menu_bar_event(self, menu_bar, event):
        """A stylesheet change (a theme switch) gives the menu bar its size
        limits back: folded again once it is polished. A menu added or
        removed (a plugin's): on the Plugins tab, or a menu TABS shows that
        was missing until now (Processing's)."""
        if event.type() != QEvent.Type.StyleChange:
            self._watch_menus()
            self._mark({self._tab_index(PLUGIN_TAB)})
            return
        if menu_bar.maximumHeight() != 0:
            QTimer.singleShot(0, lambda: self._fold_again(menu_bar))

    def _watch_menus(self):
        """Watch the menus whose items groups show, once they exist; a
        page showing one found only now is built again."""
        if self._window is None:
            return
        for name, indexes in self._menu_tabs.items():
            menu = self._menus.get(name)
            if menu is not None and not sip.isdeleted(menu):
                continue
            # A plugin's menu may have no parent (Processing's): found
            # through the menu bar.
            menu_bar = self._window.menuBar()
            menu = next((m for m in (menu_of(a) for a in (menu_bar.actions() if menu_bar is not None else ()))
                         if m is not None and m.objectName() == name), None)
            menu = menu or self._window.findChild(QMenu, name)
            if menu is None:
                continue
            self._menus[name] = menu
            self._hub.watch(menu, self, self.MENU_EVENTS, self._menu_event)
            self._mark(indexes)

    def _menu_event(self, menu, _event):
        """A command added to or removed from a menu groups show."""
        self._mark(self._menu_tabs.get(menu.objectName(), set()))

    def _fold_again(self, menu_bar):
        if self._ribbon is not None and not sip.isdeleted(menu_bar):
            menu_bar.setMaximumHeight(0)

    def _hide_new(self, toolbar):
        # After the plugin shows it (addToolBar shows toolbars it adds).
        if self._ribbon is not None and not sip.isdeleted(toolbar):
            toolbar.hide()

    def _toolbar_event(self, watched, event):
        if event.type() == QEvent.Type.ActionChanged:
            action = event.action()
            visible = action.isVisible()
            key = sip.unwrapinstance(action)
            if self._visible.get(key) is visible:
                return
            self._visible[key] = visible
        elif event.type() == QEvent.Type.ActionAdded:
            self._visible[sip.unwrapinstance(event.action())] = event.action().isVisible()
        self._changed(watched)

    def _changed(self, toolbar):
        """A toolbar's actions changed: its tabs are built again, once the
        changes of this event-loop pass are done."""
        if self._ribbon is None:
            return
        name = toolbar.objectName()
        if name == CORNER_TOOLBAR:
            indexes = {-1}
        else:
            indexes = self._tab_of.get(name) or {self._tab_index(PLUGIN_TAB)}
        self._mark(indexes)

    def _mark(self, indexes):
        """Tabs (-1: the corner) built again once this event-loop pass's
        changes are done."""
        if self._ribbon is None or not indexes:
            return
        if not self._dirty:
            QTimer.singleShot(0, self._rebuild)
        self._dirty.update(indexes)

    def _rebuild(self):
        dirty, self._dirty = self._dirty, set()
        if self._ribbon is None:
            return
        for index in dirty:
            if index == -1:
                self._fill_corner()
            else:
                self._ribbon.invalidate(index)

    @staticmethod
    def _tab_index(title):
        return next((i for i, (name, _groups) in enumerate(TABS) if name == title), len(TABS) - 1)

    # ---- Building pages ---------------------------------------------------

    def _build_page(self, index, old):
        """The page of tab `index`: its groups, and on PLUGIN_TAB a group
        per toolbar TABS does not place and one for the menus plugins add to
        the menu bar. `old`, the page it replaces, gives back the widgets it
        borrowed."""
        if old is not None:
            self._give_back(old)
            old.deleteLater()
        content = QWidget()
        content.setObjectName("studioRibbonContent")
        layout = QHBoxLayout(content)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(0)
        title, groups = TABS[index]
        self._shorts_taken = set()
        all_toolbars = self._toolbars()
        toolbars = {t.objectName(): t for t in all_toolbars if t.objectName()}
        # What "menu" sources leave out: what TABS places, every toolbar's
        # actions (on some tab) and SKIPPED_MENU_ITEMS; and, by C++ object,
        # what this page shows already.
        self._covered = self._placed_names | set(SKIPPED_MENU_ITEMS) | {
            a.objectName() for t in all_toolbars for a in t.actions() if a.objectName()}
        seen = set()
        for group in groups:
            # The group's name in QGIS's language (TABS names stay English:
            # they are keys).
            widget = self._group(content, (tr(group[0], "title"),) + tuple(group[1:]), toolbars, seen)
            if widget is not None:
                layout.addWidget(widget)
        if title == PLUGIN_TAB:
            for toolbar in all_toolbars:
                name = toolbar.objectName()
                if name in self._tab_of or name == CORNER_TOOLBAR:
                    continue
                spec = (toolbar.windowTitle() or name or tr("Plugin", "title"), ((toolbar, None),), (), AUTO)
                widget = self._group(content, spec, toolbars, seen)
                if widget is not None:
                    layout.addWidget(widget)
            menu_bar = self._window.menuBar()
            extra = [] if menu_bar is None else [
                a for a in menu_bar.actions()
                if menu_of(a) is not None and menu_of(a).objectName() not in self._menu_tabs]
            widget = self._group(content, (tr("Menus", "title"), (("actions", extra),), (), LABELS), toolbars, seen)
            if widget is not None:
                layout.addWidget(widget)
        layout.addStretch(1)
        # Never squeezed (large buttons' labels would be cut short): a page
        # wider than the window scrolls with the wheel (Ribbon.wheelEvent).
        content.setMinimumWidth(content.sizeHint().width())
        return content

    def _actions(self, sources, toolbars, seen):
        """[(action, toolbar or None)] of a group's sources, in order."""
        found = []
        for name, names in sources:
            if name == "@":
                for action_name in names:
                    action = self._window.findChild(QAction, action_name)
                    if action is None:
                        menu = self._window.findChild(QMenu, action_name)
                        action = menu.menuAction() if menu is not None else None
                    if action is not None:
                        found.append((action, None))
                continue
            if name == "actions":
                found += [(action, None) for action in names]
                continue
            if name == DROPDOWN:
                action = self._dropdown_action(names)
                if action is not None:
                    found.append((action, None))
                continue
            if name in LABEL_KINDS:
                found.append((self._label_action((name,) + tuple(names)), None))
                continue
            if name == "menu":
                for menu_name in names:
                    menu = self._menus.get(menu_name)
                    if menu is None or sip.isdeleted(menu):
                        continue
                    for action in menu.actions():
                        if (action.isSeparator() or isinstance(action, QWidgetAction)
                                or _key(action) in self._covered or sip.unwrapinstance(action) in seen):
                            continue
                        found.append((action, None))
                continue
            toolbar = name if isinstance(name, QToolBar) else toolbars.get(name)
            if toolbar is None:
                continue
            actions = [a for a in toolbar.actions() if not a.isSeparator()]
            if names is None:
                named = self._named.get(toolbar.objectName(), set()) if toolbar.objectName() else set()
                named = named | self._dropdown_names
                found += [(a, toolbar) for a in actions if a.objectName() not in named or not a.objectName()]
            else:
                by_name = {}
                for action in actions:
                    by_name.setdefault(action.objectName(), action)
                found += [(by_name[n], toolbar) for n in names if n in by_name]
        return [(a, t) for a, t in found if a.isVisible()]

    def _group(self, parent, spec, toolbars, seen):
        title, sources, large_names, layout_kind = spec[:4]
        rows = spec[4] if len(spec) > 4 else None
        entries = self._actions(sources, toolbars, seen)
        if not entries:
            return None
        seen.update(sip.unwrapinstance(action) for action, _toolbar in entries)
        large_all = layout_kind == AUTO and len(entries) <= AUTO_LARGE
        if layout_kind == AUTO:
            layout_kind = ICONS
        group = QFrame(parent)
        group.setObjectName("studioRibbonGroup")
        body = QHBoxLayout()
        body.setSpacing(SPACING)
        body.setContentsMargins(0, 0, 0, 0)
        small = []
        labelled = []
        for action, toolbar in entries:
            large = large_all or _key(action) in large_names
            first = layout_kind != LABELS and _key(action) in LABELLED_SMALL
            widget = self._widget(group, action, toolbar, "large" if large else (
                "small" if layout_kind == LABELS or first else "icon"))
            if widget is None:
                continue
            if large:
                body.addWidget(widget, 0, Qt.AlignmentFlag.AlignTop)
            elif first:
                labelled.append(widget)
            else:
                small.append((_key(action), widget))
        if small or labelled:
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(SPACING if layout_kind == ICONS and not labelled else 4)
            grid.setVerticalSpacing(ROW_SPACING)
            placed = set()
            if rows:
                by_name = {}
                for name, widget in small:
                    by_name.setdefault(name, []).append(widget)
                for row, names in enumerate(rows):
                    for column, name in enumerate(names):
                        if by_name.get(name):
                            widget = by_name[name].pop(0)
                            grid.addWidget(widget, row, column, Qt.AlignmentFlag.AlignLeft)
                            placed.add(id(widget))
            rest = [w for _n, w in small if id(w) not in placed]
            start = grid.columnCount() if placed else 0
            # The labelled most used commands first, then the icons from a
            # column of their own.
            for i, widget in enumerate(labelled):
                grid.addWidget(widget, i % ROWS, start + i // ROWS, Qt.AlignmentFlag.AlignLeft)
            if labelled:
                start += -(-len(labelled) // ROWS)
            for i, widget in enumerate(rest):
                grid.addWidget(widget, i % ROWS, start + i // ROWS, Qt.AlignmentFlag.AlignLeft)
            for row in range(ROWS):
                grid.setRowMinimumHeight(row, ROW_HEIGHT)
            body.addLayout(grid)
            body.setAlignment(grid, Qt.AlignmentFlag.AlignTop)
        if body.count() == 0:
            group.deleteLater()
            return None
        self._centre_large(group)
        self._lay_out_group(group, body, title)
        return group

    @staticmethod
    def _centre_large(group):
        """Large buttons with one-line labels: Qt keeps the icon at the
        button's top and centres the label in the room of two lines, leaving
        a gap under the icon and the pair hanging high. Half a line more
        padding above and below centres icon and label on the rows with the
        usual gap between them (the label stays put, the icon comes down),
        as a two-line button's fill them: every large button is centred on
        the middle row, one-line icons and labels all on one line."""
        large = [b for b in group.findChildren(QToolButton)
                 if b.property("studioRibbon") == "large" and "\n" not in b.text()]
        if not large:
            return
        top, bottom = LARGE_PADDING.get(DENSITY, LARGE_PADDING["standard"])
        shift = LABEL_LINE // 2
        sheet = f"QToolButton {{ padding-top: {top + shift}px; padding-bottom: {bottom + shift}px; }}"
        for button in large:
            button.setStyleSheet(sheet)

    def _lay_out_group(self, group, body, title):
        """The group's buttons (`body`) and its name where the settings put
        it: above or below them, left of them (across or reading upwards),
        or nowhere."""
        position = self._caption_position
        side = position in studio_toolbars.SIDE_MODES
        outer = QHBoxLayout(group) if side else QVBoxLayout(group)
        outer.setContentsMargins(*GROUP_MARGINS)
        outer.setSpacing(SIDE_GAP if side else SPACING)
        text = self._caption_text(title, body, position)
        caption = None
        if text:
            caption = _Caption(text, position == "left_vertical", self._caption_font, group)
        if side:
            column = QVBoxLayout()
            column.setContentsMargins(0, 0, 0, 0)
            column.addLayout(body)
            column.addStretch(1)
            if caption is not None:
                # Centred on the buttons' rows (BODY high), at their top.
                caption.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                caption.setFixedHeight(BODY)
                outer.addWidget(caption, 0, Qt.AlignmentFlag.AlignTop)
            outer.addLayout(column)
            return
        if caption is not None and position == "top":
            caption.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            outer.addWidget(caption)
        outer.addLayout(body)
        outer.addStretch(1)
        if caption is not None and position == "bottom":
            caption.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            outer.addWidget(caption)

    def _caption_text(self, title, body, position):
        """The name a group shows: none when names are off, else its full
        name, its short one (up to four letters, unique on the page), or
        with "auto" the full one where it fits: no wider than the buttons
        (across), or than their height (reading upwards, which never shows
        the full name otherwise, as toolbar names)."""
        if position not in studio_toolbars.ROW_MODES:
            return ""
        full = title.upper()
        names = self._caption_names
        if position == "left_vertical" and names == "full":
            names = "auto"
        if names == "full":
            return full
        if names == "auto":
            width = QFontMetrics(self._caption_font).horizontalAdvance(full)
            room = BODY - 4 if position == "left_vertical" else body.sizeHint().width()
            if width <= room:
                return full
        candidates = studio_toolbars.short_candidates(title)
        short = next((c for c in candidates if c not in self._shorts_taken), candidates[0] if candidates else full)
        self._shorts_taken.add(short)
        return short

    def _widget(self, parent, action, toolbar, kind):
        """The ribbon's widget for an action: a button for it, a clone of
        QGIS's tool button, or the toolbar's widget, borrowed; None for
        widgets left out."""
        spec = self._dropdown_of.get(sip.unwrapinstance(action))
        if spec is not None:
            return self._dropdown_button(parent, action, spec, kind)
        spec = self._label_of.get(sip.unwrapinstance(action))
        if spec is not None:
            label = self._label_widget(spec)
            label.setParent(parent)
            label.setFixedHeight(ROW_HEIGHT)
            return label
        shown = toolbar.widgetForAction(action) if toolbar is not None else None
        self.placed.add(sip.unwrapinstance(action))
        if isinstance(shown, QToolButton) and shown.defaultAction() is not action:
            return self._clone(parent, action, shown, kind)
        if shown is not None and not isinstance(shown, QToolButton):
            return self._borrow(parent, action, toolbar, shown)
        if isinstance(action, QWidgetAction) and shown is None and toolbar is not None:
            return None
        button = _Button(kind, parent=parent)
        button.setDefaultAction(action)
        menu = menu_of(action)
        if isinstance(shown, QToolButton):
            button.setPopupMode(shown.popupMode())
        elif menu is not None:
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        if _uses_widget_actions(menu):
            button.setMenu(_BorrowingMenu(menu, button))
        if action.icon().isNull():
            self._give_icon(button, action, kind)
        elif self._icons is not None:
            self._icons.swap_action(action)
        self._style(button, kind, label_for(_key(action), clean(action.text())))
        return button

    def _find(self, name):
        """The main window's action named `name`, or a menu's own action;
        None when there is none (yet)."""
        window = self._window
        action = window.findChild(QAction, name)
        if action is not None:
            return action
        menu = self._menus.get(name)
        if menu is None or sip.isdeleted(menu):
            menu = window.findChild(QMenu, name)
        if menu is not None:
            return menu.menuAction()
        for toolbar in self._toolbars():
            for action in toolbar.actions():
                if _key(action) == name:
                    return action
        return None

    def _dropdown_action(self, spec):
        """The action standing for dropdown `spec` (action, title, items):
        named as its own command, or its title; None while its command does
        not exist (a plugin's not loaded) and it has no title."""
        name, title, _items = spec
        main = self._find(name) if name else None
        if main is None and not title:
            return None
        action = self._dropdowns.get(spec)
        if action is None or sip.isdeleted(action):
            action = QAction(self)
            action.setObjectName(name or title)
            menu = QMenu(self._window)
            menu.setObjectName("studioRibbonDropdown")
            # Lines next to each other, or first or last, show as one or none.
            menu.setSeparatorsCollapsible(True)
            menu.aboutToShow.connect(lambda menu=menu, spec=spec: self._fill_dropdown(menu, spec))
            action.setMenu(menu)
            self._dropdowns[spec] = action
            self._dropdown_of[sip.unwrapinstance(action)] = spec
        action.setText(tr(title, "label") if title else main.text())
        return action

    def _label_action(self, spec):
        """The action standing for caption or note `spec` (kind, text, for)
        in a group (so it takes its place among the buttons)."""
        action = self._labels.get(spec)
        if action is None or sip.isdeleted(action):
            action = QAction(self)
            action.setObjectName(f"{spec[0]}:{spec[1] or ''}:{spec[2] or ''}")
            self._labels[spec] = action
            self._label_of[sip.unwrapinstance(action)] = spec
        return action

    def _label_widget(self, spec, in_menu=False, translate=True):
        """A caption's or note's label (style.qss QLabel#studioRibbonCaption,
        #studioRibbonNote, or #studioRibbonDropdownCaption in a list), its
        variables filled from the command or menu it is for."""
        kind, text, target = spec
        action = self._find(target) if target else None
        title = ""
        if action is not None:
            menu = menu_of(action)
            own = clean(menu.title() if menu is not None and not action.text() else action.text())
            title = label_for(target, own) or own
        label = QLabel(label_text(tr(text, "label") if text and translate else text, title, target))
        name = {CAPTION: "studioRibbonCaption", NOTE: "studioRibbonNote"}[kind]
        label.setObjectName("studioRibbonDropdownCaption" if in_menu and kind == CAPTION else name)
        if kind == CAPTION:
            font = label.font()
            font.setWeight(QFont.Weight.DemiBold)
            label.setFont(font)
        label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if in_menu:
            label.setContentsMargins(10, 4 if kind == CAPTION else 2, 10, 2)
        else:
            label.setContentsMargins(4, 0, 4, 0)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _fill_dropdown(self, menu, spec):
        """A dropdown's list as it opens: the commands and menus it names
        that exist now (a menu shows as a submenu, or its commands between
        lines for a name ending in CONTENTS), lines for SEPARATOR."""
        menu.clear()
        for name in spec[2]:
            if name == SEPARATOR:
                menu.addSeparator()
                continue
            if not isinstance(name, str):
                holder = QWidgetAction(menu)
                holder.setDefaultWidget(self._label_widget(name, in_menu=True))
                holder.setEnabled(False)
                menu.addAction(holder)
                continue
            source = item_menu(name)
            if source is not None:
                self._add_contents(menu, source, item_titled(name))
                continue
            action = self._find(name)
            if action is None:
                continue
            if action.icon().isNull() and self._icons is not None:
                fallback = ICON_FALLBACKS.get(name) or (GENERIC_MENU_ICON if menu_of(action) is not None else None)
                if fallback is not None and self._icons.adopt(action, fallback):
                    self._adopted.append(action)
            menu.addAction(action)

    def _add_contents(self, menu, name, titled=False):
        """Menu `name`'s commands, as it shows them now, into `menu` between
        lines (its own lines kept; widgets left out: they can be in one
        menu only); `titled`: under the menu's name, a caption that is not
        clicked (style.qss QLabel#studioRibbonDropdownCaption)."""
        action = self._find(name)
        source = menu_of(action) if action is not None else None
        if source is None or sip.isdeleted(source):
            return
        # Menus filled as they open (QGIS's recent projects...) fill now.
        source.aboutToShow.emit()
        menu.addSeparator()
        if titled and clean(source.title()):
            holder = QWidgetAction(menu)
            holder.setDefaultWidget(self._label_widget((CAPTION, clean(source.title()), None), in_menu=True,
                                                       translate=False))
            holder.setEnabled(False)
            menu.addAction(holder)
        for item in source.actions():
            if item.isSeparator():
                menu.addSeparator()
            elif item.isVisible() and not isinstance(item, QWidgetAction):
                menu.addAction(item)
        menu.addSeparator()

    def _dropdown_button(self, parent, action, spec, kind):
        """A dropdown's button: its own command on its face and the list
        behind the arrow, or (without a command) the list on a click."""
        name, title, _items = spec
        main = self._find(name) if name else None
        button = _Button(kind, parent=parent)
        if main is not None:
            self.placed.add(sip.unwrapinstance(main))
            button.setDefaultAction(main)
            button.setMenu(menu_of(action))
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            if main.icon().isNull():
                self._give_icon(button, main, kind)
            elif self._icons is not None:
                self._icons.swap_action(main)
            label = tr(title, "label") if title else label_for(_key(main), clean(main.text()))
        else:
            button.setDefaultAction(action)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self._give_icon(button, action, kind)
            label = tr(title, "label")
        self._style(button, kind, label)
        return button

    def _give_icon(self, button, action, kind):
        """A command QGIS gives no icon (most only in its menus): one of the
        theme's (ICON_FALLBACKS), or an empty one keeping labels in line."""
        name = ICON_FALLBACKS.get(_key(action)) or (GENERIC_MENU_ICON if menu_of(action) is not None else None)
        if name is not None and self._icons is not None and self._icons.adopt(action, name):
            self._adopted.append(action)
        elif kind != "icon":
            button.set_placeholder(LARGE_ICON if kind == "large" else SMALL_ICON)

    def _clone(self, parent, action, source, kind):
        """A button standing for one of QGIS's tool buttons (a tool picked
        from its menu becomes its default): the same tools, the chosen one
        passed back to QGIS's button (its own handler remembers it)."""
        button = _Button(kind, parent=parent)
        menu = menu_of(source)
        if menu is not None:
            button.setMenu(_BorrowingMenu(menu, button) if _uses_widget_actions(menu) else menu)
        else:
            button.addActions(source.actions())
        button.setPopupMode(source.popupMode())
        default = source.defaultAction()
        if default is not None:
            button.setDefaultAction(default)
            button.follow(source)
        else:
            button.setIcon(source.icon())
            button.setToolTip(source.toolTip())
            button.clicked.connect(source.click)

        def chosen(picked, button=button, source=source):
            if sip.isdeleted(source) or sip.isdeleted(button):
                return
            if picked is not source.defaultAction():
                source.triggered.emit(picked)
            button.sync()

        button.triggered.connect(chosen)
        label = label_for(action.objectName(), clean(default.text() if default else source.toolTip()))
        self._style(button, kind, label)
        return button

    def _borrow(self, parent, action, toolbar, widget):
        """A toolbar's own widget (a spin box, a combo box...), moved here
        while the ribbon shows; None for SKIPPED_WIDGETS and empty ones."""
        if widget.metaObject().className() in SKIPPED_WIDGETS or widget.sizeHint().width() <= 0:
            return None
        for entry in self._borrowed:
            if entry[0] is widget:
                self._borrowed.remove(entry)
                break
        self._borrowed.append((widget, toolbar, action))
        widget.setParent(parent)
        widget.setFixedHeight(ROW_HEIGHT)
        widget.show()
        return widget

    def _give_back(self, page=None):
        """Widgets borrowed (on `page`, or all) go back to their toolbars."""
        keep = []
        for widget, toolbar, action in self._borrowed:
            if sip.isdeleted(widget) or sip.isdeleted(toolbar):
                continue
            if page is not None and not page.isAncestorOf(widget):
                keep.append((widget, toolbar, action))
                continue
            widget.setParent(toolbar)
            widget.setMinimumHeight(0)
            widget.setMaximumHeight(16777215)
            widget.setVisible(action.isVisible())
            if toolbar.layout() is not None:
                toolbar.layout().invalidate()
        self._borrowed = keep

    @staticmethod
    def _style(button, kind, label):
        if kind == "large":
            button.setIconSize(QSize(LARGE_ICON, LARGE_ICON + ICON_GAP))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.set_label(two_lines(label))
            button.setFixedHeight(BODY)
            button.setMinimumWidth(LARGE_MIN_WIDTH)
        elif kind == "small":
            button.setIconSize(QSize(SMALL_ICON + ICON_GAP, SMALL_ICON))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.set_label(label)
            button.setFixedHeight(ROW_HEIGHT)
        else:
            button.setIconSize(QSize(SMALL_ICON, SMALL_ICON))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setFixedHeight(ROW_HEIGHT)
            button.setMinimumWidth(ROW_HEIGHT + 4)
        button._gap_icon()  # pylint: disable=protected-access

    def _fill_corner(self):
        """The Help toolbar's buttons right of the tabs."""
        if self._corner is None:
            return
        layout = self._corner.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        toolbar = next((t for t in self._toolbars() if t.objectName() == CORNER_TOOLBAR), None)
        if toolbar is None:
            return
        for action in toolbar.actions():
            if action.isSeparator() or not action.isVisible():
                continue
            widget = self._widget(self._corner, action, toolbar, "icon")
            if widget is None:
                continue
            if isinstance(widget, QToolButton) and SMALL_ICON > CORNER_ICON:
                # In the tab row: never taller than the medium size's.
                widget.setIconSize(QSize(CORNER_ICON, CORNER_ICON))
                widget.setFixedHeight(CORNER_ICON + ROW_HEIGHT - SMALL_ICON)
                widget.setMinimumWidth(CORNER_ICON + ROW_HEIGHT - SMALL_ICON + 4)
            layout.addWidget(widget)

