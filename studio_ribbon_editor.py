"""The ribbon editor (Plugins > QGIS Studio Themes > Ribbon Editor…): edits
the ribbon's tabs, groups and buttons and saves them to the profile's own
ribbon.yaml (studio_ribbon.user_tabs_file), which the ribbon reads the next
time QGIS starts.

Two views of the same file:

- Visual: the ribbon as a tree (tab > group > button) beside every command
  QGIS has, by toolbar and by menu. Commands are dragged onto groups,
  dragged within the tree to reorder or move them, and dragged back (or
  deleted) to take them off. A tick in the Large column makes a button
  large. Commands already on the ribbon are greyed in the list. A dropdown
  is a button with a list of its own: commands dropped on it go into its
  list (menus show as submenus, or their commands right in the list:
  "contents" items, e.g. the recent projects), and its own command, if it
  has one, is on its face. Captions and notes are texts of one's own in a
  group's rows or a dropdown's list, never clicked; {title} and {id} in
  them stand for the label and objectName of the command they are for.
- YAML: the file as text (format in ribbon.yaml's header), checked before it
  is used.

The tree's entries map onto ribbon.yaml's sources: a command of a toolbar
("toolbar:" with "actions:"), a command of the main window ("main:"), a
toolbar's other buttons ("toolbar:" without "actions:"), a menu's other
commands ("menu:") and a dropdown ("dropdown:"). Consecutive entries of one kind are written as one
source. Saving from the YAML view keeps the text as typed (comments too);
the visual view writes the file in ribbon.yaml's own layout.
"""
import json
import os

import yaml
from qgis.PyQt import sip
from qgis.PyQt.QtCore import (
    QDir, QDirIterator, QItemSelectionModel, QMimeData, QProcess, QRegularExpression, QSize, Qt, QTimer, QUrl,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QBrush, QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPalette, QPixmap, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QAction, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QToolBar,
    QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout, QWidget, QWidgetAction,
)

from . import studio_ribbon
from .studio_events import menu_of
from .studio_i18n import tr

MIME = "application/x-studio-ribbon-entries"
ROLE = Qt.ItemDataRole.UserRole
# Palette rows shown for information only (commands without objectName).
INFO_ROLE = Qt.ItemDataRole.UserRole + 1
# Tree levels: a tab, a group, an entry (a button or a source of buttons),
# an item of a dropdown's list.
TAB, GROUP, ENTRY, ITEM = 0, 1, 2, 3
# Entry kinds: a command (an action or a menu shown as a button), a
# toolbar's other buttons, a menu's other commands, a dropdown; and the
# items of a dropdown's list (a name, or SEPARATOR).
CMD, REST, MENU, DROP, LISTED = "cmd", "rest", "menu", "dropdown", "item"
SEPARATOR = studio_ribbon.SEPARATOR
CONTENTS = studio_ribbon.CONTENTS
TITLED = studio_ribbon.TITLED
item_menu = studio_ribbon.item_menu
item_titled = studio_ribbon.item_titled
# Captions and notes: {"kind": CAPTION or NOTE, "text", "for"} (either may
# be None), in a group or in a dropdown's list.
CAPTION, NOTE = studio_ribbon.CAPTION, studio_ribbon.NOTE
LABEL_KINDS = studio_ribbon.LABEL_KINDS


def label_entry(kind, value):
    """A caption or note of ribbon.yaml (text, or a mapping) as an entry."""
    value = {"text": value} if isinstance(value, str) else (value or {})
    return {"kind": kind, "text": value.get("text"), "for": value.get("for")}


def label_yaml(entry):
    """A caption or note entry as ribbon.yaml has it."""
    return {entry["kind"]: {k: entry[k] for k in ("text", "for") if entry.get(k)}}


def _dropdown_items(items):
    """A dropdown's items with captions and notes in one shape."""
    out = []
    for item in items or ():
        if isinstance(item, dict):
            kind = next(iter(item))
            item = label_yaml(label_entry(kind, item[kind]))
        out.append(item)
    return out


def entry_key(entry):
    """The name `large` and `rows` know an entry by: a command's name, a
    dropdown's command or else its title; None for the others."""
    if entry["kind"] == CMD:
        return entry["name"]
    if entry["kind"] == DROP:
        return entry.get("action") or entry.get("title")
    return None
# The tree's tick columns: the group's list each one sets.
TICKS = {2: "large", 3: "labelled"}
# Lists of names written on one line up to this width.
LINE_WIDTH = 100


def _t(text):
    """The editor's own texts in QGIS's language (studio_i18n, context
    "editor")."""
    return tr(text, "editor")


# ---- The model: ribbon.yaml's data <-> tabs of entries --------------------
# Pure Python (no Qt), so they can be checked outside QGIS.

def tabs_from_data(data):
    """ribbon.yaml's parsed `data` as [{"title", "groups": [{"title",
    "layout", "large", "labelled", "rows", "entries": [entry]}]}]; an entry is {"kind":
    CMD, "name", "toolbar" (or None)}, {"kind": REST, "toolbar"},
    {"kind": MENU, "name"} or {"kind": DROP, "action", "title" (either may
    be None), "items": [names]}."""
    tabs = []
    for tab in data["tabs"]:
        groups = []
        for group in tab.get("groups") or []:
            entries = []
            for source in group.get("sources") or []:
                if "toolbar" in source:
                    if source.get("actions") is None:
                        entries.append({"kind": REST, "toolbar": source["toolbar"]})
                    else:
                        entries += [{"kind": CMD, "name": n, "toolbar": source["toolbar"]} for n in source["actions"]]
                elif "main" in source:
                    entries += [{"kind": CMD, "name": n, "toolbar": None} for n in source["main"]]
                elif "menu" in source:
                    entries += [{"kind": MENU, "name": n} for n in source["menu"]]
                elif "dropdown" in source:
                    spec = source["dropdown"]
                    entries.append({"kind": DROP, "action": spec.get("action"), "title": spec.get("title"),
                                    "items": _dropdown_items(spec.get("items"))})
                else:
                    entries += [label_entry(k, source[k]) for k in LABEL_KINDS if k in source][:1]
            groups.append({
                "title": group["title"], "layout": group.get("layout", studio_ribbon.LABELS),
                "large": list(group.get("large") or ()), "labelled": list(group.get("labelled") or ()),
                "rows": [list(r) for r in group.get("rows") or ()],
                "entries": entries,
            })
        tabs.append({"title": tab["title"], "groups": groups})
    return tabs


def data_from_tabs(tabs):
    """ribbon.yaml's data of `tabs` (as tabs_from_data gives them)."""
    out = []
    for tab in tabs:
        groups = []
        for group in tab["groups"]:
            sources = []
            for entry in group["entries"]:
                last = sources[-1] if sources else None
                if entry["kind"] == REST:
                    sources.append({"toolbar": entry["toolbar"]})
                elif entry["kind"] in LABEL_KINDS:
                    sources.append(label_yaml(entry))
                elif entry["kind"] == DROP:
                    spec = {k: entry[k] for k in ("action", "title") if entry.get(k)}
                    spec["items"] = _dropdown_items(entry.get("items"))
                    sources.append({"dropdown": spec})
                elif entry["kind"] == MENU:
                    if last is not None and "menu" in last:
                        last["menu"].append(entry["name"])
                    else:
                        sources.append({"menu": [entry["name"]]})
                elif entry["toolbar"]:
                    if last is not None and last.get("toolbar") == entry["toolbar"] and "actions" in last:
                        last["actions"].append(entry["name"])
                    else:
                        sources.append({"toolbar": entry["toolbar"], "actions": [entry["name"]]})
                elif last is not None and "main" in last:
                    last["main"].append(entry["name"])
                else:
                    sources.append({"main": [entry["name"]]})
            item = {"title": group["title"], "sources": sources}
            if group.get("large"):
                item["large"] = list(dict.fromkeys(group["large"]))
            if group.get("labelled"):
                item["labelled"] = list(dict.fromkeys(group["labelled"]))
            item["layout"] = group.get("layout") or studio_ribbon.LABELS
            rows = [list(r) for r in group.get("rows") or () if r]
            if rows:
                item["rows"] = rows
            groups.append(item)
        out.append({"title": tab["title"], "groups": groups})
    return {"tabs": out}


def _quoted(text):
    # A JSON string is a valid YAML double-quoted scalar.
    return json.dumps(text, ensure_ascii=False)


def _names(lines, indent, key, names):
    """`key: [names]` on one line when it fits, else one name per line."""
    flow = "[" + ", ".join(_quoted(n) for n in names) + "]"
    if len(indent) + len(key) + 2 + len(flow) <= LINE_WIDTH or not names:
        lines.append(f"{indent}{key}: {flow}")
        return
    lines.append(f"{indent}{key}:")
    inner = indent + " " * (4 if key.startswith("- ") else 2)
    lines += [f"{inner}- {_quoted(n)}" for n in names]


def header(path=studio_ribbon.TABS_FILE):
    """The comment lines ribbon.yaml starts with (its format)."""
    lines = []
    try:
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                if not line.startswith("#"):
                    break
                lines.append(line.rstrip("\n"))
    except OSError:
        pass
    return lines


def dump(data, head=None):
    """ribbon.yaml's text of `data`, in the layout of the plugin's file."""
    lines = list(header() if head is None else head)
    if lines:
        lines.append("")
    lines.append("tabs:")
    for tab in data["tabs"]:
        lines.append(f"  - title: {_quoted(tab['title'])}")
        if not tab["groups"]:
            lines.append("    groups: []")
            continue
        lines.append("    groups:")
        for group in tab["groups"]:
            lines.append(f"      - title: {_quoted(group['title'])}")
            if not group["sources"]:
                lines.append("        sources: []")
            else:
                lines.append("        sources:")
            for source in group["sources"]:
                if "toolbar" in source:
                    lines.append(f"          - toolbar: {_quoted(source['toolbar'])}")
                    if "actions" in source:
                        _names(lines, "            ", "actions", source["actions"])
                elif "dropdown" in source:
                    spec = source["dropdown"]
                    lines.append("          - dropdown:")
                    for key in ("action", "title"):
                        if spec.get(key):
                            lines.append(f"              {key}: {_quoted(spec[key])}")
                    _names(lines, "              ", "items", spec.get("items") or [])
                elif any(kind in source for kind in LABEL_KINDS):
                    kind = next(kind for kind in LABEL_KINDS if kind in source)
                    lines.append(f"          - {kind}: {_quoted(source[kind])}")
                else:
                    key = "main" if "main" in source else "menu"
                    _names(lines, "          ", f"- {key}", source[key])
            if group.get("large"):
                _names(lines, "        ", "large", group["large"])
            if group.get("labelled"):
                _names(lines, "        ", "labelled", group["labelled"])
            lines.append(f"        layout: {group['layout']}")
            if group.get("rows"):
                lines.append("        rows:")
                for row in group["rows"]:
                    _row(lines, row)
    for section in ("labels", "icons"):
        if data.get(section):
            lines.append("")
            lines.append(f"{section}:")
            lines += [f"  {_quoted(k)}: {_quoted(v)}" for k, v in data[section].items()]
    return "\n".join(lines) + "\n"


def _row(lines, row):
    flow = "[" + ", ".join(_quoted(n) for n in row) + "]"
    if 12 + len(flow) <= LINE_WIDTH:
        lines.append(f"          - {flow}")
    else:
        lines.append("          -")
        lines += [f"              - {_quoted(n)}" for n in row]


def check_text(text):
    """None when ribbon.yaml's `text` reads, else (message, line or None)."""
    try:
        studio_ribbon.read_tabs_text(text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        return str(error), (mark.line if mark is not None else None)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        return str(error), None
    return None


# ---- What QGIS has --------------------------------------------------------

class Catalog:
    """The main window's commands: its toolbars' actions and its menus',
    by objectName (studio_ribbon._key), with their labels and icons."""

    def __init__(self, window):
        self._window = window
        self.actions = {}
        # [(objectName, title, [action names])], toolbar of each action.
        self.toolbars = []
        self.toolbar_titles = {}
        self.toolbar_of = {}
        for toolbar in window.findChildren(QToolBar, options=Qt.FindChildOption.FindDirectChildrenOnly):
            name = toolbar.objectName()
            if not name or name == studio_ribbon.HOST_NAME:
                continue
            names = []
            for action in toolbar.actions():
                key = studio_ribbon._key(action)  # pylint: disable=protected-access
                if action.isSeparator() or not key or key in names:
                    continue
                names.append(key)
                self.actions.setdefault(key, action)
                self.toolbar_of.setdefault(key, name)
            self.toolbars.append((name, toolbar.windowTitle() or name, names))
            self.toolbar_titles[name] = toolbar.windowTitle() or name
        # [(menu objectName, title, children)]; a child is (action name,
        # None) or a menu's (name, title, children).
        self.menus = []
        self.menu_titles = {}
        # {menu objectName: [(text, icon)]} of commands without objectName.
        self.unnamed = {}
        seen = set()
        menu_bar = window.menuBar()
        for action in menu_bar.actions() if menu_bar is not None else ():
            menu = menu_of(action)
            if menu is not None and menu.objectName():
                self.menus.append(self._menu(menu, seen))

    def _menu(self, menu, seen):
        seen.add(sip.unwrapinstance(menu))
        name = menu.objectName()
        self.actions.setdefault(name, menu.menuAction())
        self.menu_titles[name] = studio_ribbon.clean(menu.title()) or name
        children = []
        for action in menu.actions():
            if action.isSeparator() or isinstance(action, QWidgetAction):
                continue
            sub = menu_of(action)
            if sub is not None and sub.objectName():
                if sip.unwrapinstance(sub) not in seen:
                    children.append(self._menu(sub, seen))
            elif action.objectName():
                self.actions.setdefault(action.objectName(), action)
                children.append((action.objectName(), None))
            elif studio_ribbon.clean(action.text()):
                # No objectName (many plugins' commands): ribbon.yaml cannot
                # name it; the menu's "everything else" shows it.
                self.unnamed.setdefault(name, []).append((studio_ribbon.clean(action.text()), action.icon()))
        return name, self.menu_titles[name], children

    def action(self, name):
        """The action named `name` (a menu's own action for a menu), or None."""
        action = self.actions.get(name)
        if action is not None and not sip.isdeleted(action):
            return action
        action = self._window.findChild(QAction, name)
        if action is None:
            menu = self._window.findChild(QMenu, name)
            action = menu.menuAction() if menu is not None else None
        if action is not None:
            self.actions[name] = action
        return action

    def label(self, name):
        """The label the ribbon gives command `name`, and its full text."""
        action = self.action(name)
        own = studio_ribbon.clean(action.text()) if action is not None else ""
        # Without the running ribbon's own labels: (the editor shows its own).
        return studio_ribbon.label_for(name, own, override=False) or own or name, own

    def icon(self, name):
        action = self.action(name)
        return action.icon() if action is not None else None

    def found(self, name):
        return self.action(name) is not None


# ---- The YAML view ----------------------------------------------------------

class _YamlHighlighter(QSyntaxHighlighter):
    """Comments, keys and quoted names of ribbon.yaml in colours of their own."""

    def __init__(self, document, palette):
        super().__init__(document)
        dark = palette.color(QPalette.ColorRole.Base).lightness() < 128
        self._rules = []
        for pattern, color, bold in (
                (r'"(?:[^"\\]|\\.)*"', "#8fc97a" if dark else "#3b7d23", False),
                (r"^\s*(?:-\s+)?[A-Za-z_]+(?=:)", "#7fb4ff" if dark else "#1f5fbf", True),
                (r"[&*][A-Za-z_]\w*", "#e0a050" if dark else "#a0581b", False),
                (r"#.*$", palette.color(QPalette.ColorRole.PlaceholderText).name(), False)):
            text_format = QTextCharFormat()
            text_format.setForeground(QColor(color))
            if bold:
                text_format.setFontWeight(QFont.Weight.DemiBold)
            self._rules.append((QRegularExpression(pattern), text_format))

    def highlightBlock(self, text):  # pylint: disable=invalid-name
        for expression, text_format in self._rules:
            matches = expression.globalMatch(text)
            while matches.hasNext():
                match = matches.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), text_format)


# ---- The visual view ------------------------------------------------------

def listed(entry):
    """A dropdown's item for a palette or group entry: a command or menu by
    name; a menu's "everything else" as its contents; a caption or note as
    it is."""
    if entry["kind"] in LABEL_KINDS:
        return dict(entry)
    if entry["kind"] == MENU:
        return {"kind": LISTED, "name": entry["name"] + CONTENTS}
    return {"kind": LISTED, "name": entry["name"]}


def _share_columns(tree, shares):
    """Columns as fixed shares of the tree's width: the trailing ones sized
    to contents (tick columns) fit their titles, the last other one takes
    the rest, so they line up whatever the window's size."""
    header = tree.header()
    width = tree.viewport().width()
    last = header.count() - 1
    while last > len(shares) and header.sectionResizeMode(last) == QHeaderView.ResizeMode.ResizeToContents:
        width -= header.sectionSize(last)
        last -= 1
    header.setStretchLastSection(False)
    used = 0
    for column, share in enumerate(shares):
        size = int(width * share)
        header.resizeSection(column, size)
        used += size
    header.resizeSection(last, max(40, width - used))


def _depth(item):
    depth = 0
    while item.parent() is not None:
        item = item.parent()
        depth += 1
    return depth


def _children(item):
    return [item.child(i) for i in range(item.childCount())]


class _Palette(QTreeWidget):
    """Every command QGIS has, dragged from here onto the ribbon's tree;
    entries of the tree dropped here are taken off the ribbon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tree = None
        self.setHeaderLabels([_t("Command"), _t("Name")])
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setUniformRowHeights(True)
        _share_columns(self, (0.62,))

    def resizeEvent(self, event):  # pylint: disable=invalid-name
        super().resizeEvent(event)
        _share_columns(self, (0.62,))

    def mimeTypes(self):  # pylint: disable=invalid-name
        return [MIME]

    def mimeData(self, items):  # pylint: disable=invalid-name
        entries = [item.data(0, ROLE) for item in items if item.data(0, ROLE)]
        data = QMimeData()
        data.setData(MIME, json.dumps(entries).encode("utf-8"))
        return data

    def supportedDropActions(self):  # pylint: disable=invalid-name
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def _from_tree(self, event):
        return self.tree is not None and event.source() is self.tree

    def dragEnterEvent(self, event):  # pylint: disable=invalid-name
        if self._from_tree(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # pylint: disable=invalid-name
        self.dragEnterEvent(event)

    def dropEvent(self, event):  # pylint: disable=invalid-name
        if not self._from_tree(event):
            event.ignore()
            return
        # Copy, so the tree's own drag removes nothing: it is removed here.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.tree.remove_selected()


class _RibbonTree(QTreeWidget):
    """The ribbon as tabs > groups > entries. Entries come from the palette
    (MIME) or move within the tree; an item only lands at its own level."""

    changed = pyqtSignal()

    def __init__(self, make_entry, parent=None):
        super().__init__(parent)
        self._make_entry = make_entry
        self.setHeaderLabels([_t("Ribbon"), _t("Name / source"), _t("Large"), _t("Labelled")])
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setUniformRowHeights(True)
        self.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        _share_columns(self, (0.55,))
        self.itemDoubleClicked.connect(self._double_clicked)

    def resizeEvent(self, event):  # pylint: disable=invalid-name
        super().resizeEvent(event)
        _share_columns(self, (0.55,))

    # Titles are edited in place (double-click or F2), the other columns not.
    def _double_clicked(self, item, _column):
        if _depth(item) in (TAB, GROUP):
            self.editItem(item, 0)

    def keyPressEvent(self, event):  # pylint: disable=invalid-name
        item = self.currentItem()
        if event.key() == Qt.Key.Key_F2 and item is not None and _depth(item) in (TAB, GROUP):
            self.editItem(item, 0)
            return
        if event.key() == Qt.Key.Key_Delete:
            self.remove_selected()
            return
        super().keyPressEvent(event)

    def mimeTypes(self):  # pylint: disable=invalid-name
        return [MIME]

    def mimeData(self, items):  # pylint: disable=invalid-name
        data = QMimeData()
        data.setData(MIME, b"[]")
        return data

    def supportedDropActions(self):  # pylint: disable=invalid-name
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    # ---- Dropping -----------------------------------------------------------

    def _dragged(self):
        """The selected items of the topmost level selected, in tree order,
        none inside another."""
        selected = self.selectedItems()
        if not selected:
            return None, []
        level = min(_depth(i) for i in selected)
        chosen = {id(i) for i in selected if _depth(i) == level}
        items = []
        iterator = QTreeWidgetItemIterator(self)
        while iterator.value() is not None:
            if id(iterator.value()) in chosen:
                items.append(iterator.value())
            iterator += 1
        return level, items

    def _target(self, level, event):
        """(parent item, index) where items of `level` dropped at the event's
        position go, or None."""
        root = self.invisibleRootItem()
        item = self.itemAt(event.position().toPoint())
        where = self.dropIndicatorPosition()
        Indicator = QAbstractItemView.DropIndicatorPosition
        if item is None:
            parent = root
            for _ in range(level):
                if parent.childCount() == 0:
                    return None
                parent = parent.child(parent.childCount() - 1)
            return parent, parent.childCount()
        depth = _depth(item)
        if depth > level:
            while _depth(item) > level:
                item = item.parent()
            parent = item.parent() or root
            return parent, parent.indexOfChild(item) + 1
        if depth == level:
            parent = item.parent() or root
            index = parent.indexOfChild(item)
            return parent, index + (0 if where == Indicator.AboveItem else 1)
        if depth == level - 1:
            if where == Indicator.AboveItem:
                parent = item.parent() or root
                index = parent.indexOfChild(item)
                if index == 0:
                    return None
                before = parent.child(index - 1)
                return before, before.childCount()
            if where == Indicator.BelowItem and item.isExpanded() and item.childCount():
                return item, 0
            return item, item.childCount()
        # An entry dropped on a tab: into its last group.
        if item.childCount():
            last = item.child(item.childCount() - 1)
            return last, last.childCount()
        return None

    def _payload(self, event):
        """(level, items to move) for a drag inside the tree, (ENTRY,
        entries) for one from the palette, else (None, None)."""
        if event.source() is self:
            level, items = self._dragged()
            return level, items
        if event.mimeData().hasFormat(MIME):
            try:
                entries = json.loads(bytes(event.mimeData().data(MIME)).decode("utf-8"))
            except ValueError:
                return None, None
            return (ENTRY, entries) if entries else (None, None)
        return None, None

    def _dropdown_spot(self, event):
        """(dropdown item, index) when the event points into a dropdown's
        list (on the dropdown, or at one of its items), else None."""
        item = self.itemAt(event.position().toPoint())
        if item is None:
            return None
        Indicator = QAbstractItemView.DropIndicatorPosition
        where = self.dropIndicatorPosition()
        if _depth(item) == ITEM:
            parent = item.parent()
            return parent, parent.indexOfChild(item) + (0 if where == Indicator.AboveItem else 1)
        if _depth(item) == ENTRY and item.data(0, ROLE)["kind"] == DROP:
            if where == Indicator.OnItem:
                return item, item.childCount()
            if where == Indicator.BelowItem and item.isExpanded() and item.childCount():
                return item, 0
        return None

    def _plan(self, event):
        """(how, payload, parent, index) of a drop, or None. How: "move"
        (items keep their level), "add" (palette entries), "into" (commands
        into a dropdown's list), "out" (a dropdown's items onto a group)."""
        level, payload = self._payload(event)
        if level is None or not payload:
            return None
        inside = event.source() is self
        if level in (ENTRY, ITEM):
            spot = self._dropdown_spot(event)
            if spot is not None:
                if level == ITEM:
                    return ("move", payload) + spot if inside else None
                kinds = {(p.data(0, ROLE) if inside else p)["kind"] for p in payload}
                if kinds <= {CMD, MENU, CAPTION, NOTE}:
                    return ("into", payload) + spot
            if level == ITEM:
                target = self._target(ENTRY, event)
                return ("out", payload) + target if target is not None and inside else None
        target = self._target(level, event)
        if target is None:
            return None
        return ("move" if inside else "add", payload) + target

    def dragEnterEvent(self, event):  # pylint: disable=invalid-name
        level, payload = self._payload(event)
        if level is None or not payload:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dragMoveEvent(self, event):  # pylint: disable=invalid-name
        super().dragMoveEvent(event)
        if self._plan(event) is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dropEvent(self, event):  # pylint: disable=invalid-name
        plan = self._plan(event)
        # Never MoveAction: Qt would then remove the dragged rows itself.
        event.setDropAction(Qt.DropAction.CopyAction)
        if plan is None:
            event.ignore()
            return
        event.accept()
        how, payload, parent, index = plan
        if how == "move":
            self.move_items(payload, parent, index)
        elif how == "add":
            self.add_entries(payload, parent, index)
        elif how == "into":
            entries = [p.data(0, ROLE) if isinstance(p, QTreeWidgetItem) else p for p in payload]
            if isinstance(payload[0], QTreeWidgetItem):
                self._take(payload)
            self.add_entries([listed(e) for e in entries], parent, index)
        else:
            entries = [p.data(0, ROLE) for p in payload]
            self._take(payload)
            self.add_entries([dict(e) if e["kind"] in LABEL_KINDS else
                              {"kind": MENU, "name": item_menu(e["name"])} if item_menu(e["name"]) else
                              {"kind": CMD, "name": e["name"], "toolbar": self.toolbar_of(e["name"])}
                              for e in entries if e.get("name") != SEPARATOR], parent, index)

    def _take(self, items):
        root = self.invisibleRootItem()
        for item in items:
            (item.parent() or root).removeChild(item)

    @staticmethod
    def toolbar_of(_name):
        """The toolbar a command dragged out of a dropdown comes from (set
        by the dialog); None: the main window's."""
        return None

    # ---- Changes ----------------------------------------------------------

    def move_items(self, items, parent, index):
        root = self.invisibleRootItem()
        expanded = {id(i): i.isExpanded() for item in items for i in [item] + self._all_below(item)}
        for item in items:
            old_parent = item.parent() or root
            old_index = old_parent.indexOfChild(item)
            if old_parent is parent and old_index < index:
                index -= 1
            old_parent.takeChild(old_index)
            parent.insertChild(index, item)
            index += 1
        for item in items:
            for each in [item] + self._all_below(item):
                each.setExpanded(expanded.get(id(each), False))
        self.clearSelection()
        for item in items:
            item.setSelected(True)
        if items:
            self.setCurrentItem(items[0], 0, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.changed.emit()

    @staticmethod
    def _all_below(item):
        found = []
        for child in _children(item):
            found.append(child)
            found += _RibbonTree._all_below(child)
        return found

    @staticmethod
    def _identity(entry):
        """What makes two entries the same: dropdowns and lines never are."""
        if entry["kind"] in (DROP,) + LABEL_KINDS or entry.get("name") == SEPARATOR:
            return object()
        return entry["kind"], entry.get("toolbar") if entry["kind"] == REST else entry.get("name")

    def add_entries(self, entries, group, index=None):
        """Add `entries` to `group` at `index` (default: its end), leaving out
        those the group shows already."""
        have = {self._identity(c.data(0, ROLE)) for c in _children(group)}
        index = group.childCount() if index is None else index
        added = []
        for entry in entries:
            key = self._identity(entry)
            if key in have:
                continue
            have.add(key)
            item = self._make_entry(entry, group)
            group.insertChild(index, item)
            index += 1
            added.append(item)
        group.setExpanded(True)
        if added:
            self.clearSelection()
            for item in added:
                item.setSelected(True)
            self.scrollToItem(added[-1])
            self.changed.emit()
        return added

    def remove_selected(self):
        _level, items = self._dragged()
        self._take(items)
        if items:
            self.changed.emit()


class IconPicker(QDialog):
    """Choose an icon from those this QGIS session has: QGIS's theme, the
    commands' own (each window command's icon), Qt resources plugins load
    (":/plugins/..."), or a file. `spec` is the choice, as ribbon.yaml's
    icons: has it (studio_ribbon.icon_from_spec)."""

    SETS = (("all", "All"), ("theme", "QGIS theme"), ("commands", "Commands"), ("plugins", "Plugins"))

    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("Choose an Icon"))
        self.spec = None
        self._search = QLineEdit()
        self._search.setPlaceholderText(_t("Search icons…"))
        self._search.setClearButtonEnabled(True)
        self._set = QComboBox()
        for value, text in self.SETS:
            self._set.addItem(_t(text), value)
        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(32, 32))
        self._list.setGridSize(QSize(96, 72))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setUniformItemSizes(True)
        self._list.setWordWrap(True)
        self._list.itemDoubleClicked.connect(lambda *_args: self._choose())
        self._fill(catalog)
        self._search.textChanged.connect(self._filter)
        self._set.currentIndexChanged.connect(self._filter)
        file_button = QPushButton(_t("From File…"))
        file_button.clicked.connect(self._from_file)
        choose = QPushButton(_t("Choose"))
        choose.setDefault(True)
        choose.clicked.connect(self._choose)
        cancel = QPushButton(_t("Cancel"))
        cancel.clicked.connect(self.reject)
        top = QHBoxLayout()
        top.addWidget(self._search, 1)
        top.addWidget(self._set)
        bottom = QHBoxLayout()
        bottom.addWidget(file_button)
        bottom.addStretch(1)
        bottom.addWidget(choose)
        bottom.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._list, 1)
        layout.addLayout(bottom)
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        free = screen.availableGeometry()
        self.resize(min(820, int(free.width() * 0.8)), min(600, int(free.height() * 0.75)))

    def _add(self, kind, spec, icon, text, tip):
        if icon is None or icon.isNull():
            return
        item = QListWidgetItem(icon, text)
        item.setData(ROLE, spec)
        item.setData(ROLE + 1, kind)
        item.setToolTip(tip)
        self._list.addItem(item)

    def _fill(self, catalog):
        for path in _resources(studio_ribbon.THEME_ICONS.rstrip("/")):
            name = path[len(studio_ribbon.THEME_ICONS):]
            self._add("theme", path, QIcon(path), os.path.splitext(os.path.basename(name))[0], name)
        for name in sorted(catalog.actions, key=lambda n: catalog.label(n)[0].lower()):
            label = catalog.label(name)[0]
            self._add("commands", studio_ribbon.ACTION_ICON + name, catalog.icon(name), label, f"{label}  ({name})")
        for path in _resources(":/plugins"):
            self._add("plugins", path, QIcon(path), os.path.splitext(os.path.basename(path))[0], path)

    def _filter(self, *_args):
        words = self._search.text().strip().lower().split()
        chosen = self._set.currentData()
        for row in range(self._list.count()):
            item = self._list.item(row)
            text = f"{item.text()} {item.toolTip()}".lower()
            item.setHidden(not ((chosen == "all" or item.data(ROLE + 1) == chosen)
                                and all(w in text for w in words)))

    def _choose(self):
        item = self._list.currentItem()
        if item is None or item.isHidden():
            return
        self.spec = item.data(ROLE)
        self.accept()

    def _from_file(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, _t("Choose an Icon"), "", _t("Icons (*.svg *.png)"))
        if path:
            self.spec = path
            self.accept()


def _resources(root):
    """The SVG and PNG files under Qt resource folder `root`, sorted."""
    found = []
    iterator = QDirIterator(root, ["*.svg", "*.png"], QDir.Filter.Files,
                            QDirIterator.IteratorFlag.Subdirectories)
    while iterator.hasNext():
        found.append(iterator.next())
    return sorted(found, key=str.lower)


class RibbonEditorDialog(QDialog):
    """See the module docstring."""

    # ribbon.yaml was saved: the ribbon reads it again (the plugin).
    saved = pyqtSignal()

    LAYOUTS = (
        (studio_ribbon.LABELS, "Labelled buttons"),
        (studio_ribbon.ICONS, "Icons only"),
        (studio_ribbon.AUTO, "Auto"),
    )

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("Ribbon Editor"))
        self._fit_screen(parent)
        self._catalog = Catalog(iface.mainWindow())
        self._path = studio_ribbon.user_tabs_file()
        # The text last loaded or saved, and whether each view changed
        # since the two last matched.
        self._saved = ""
        self._tree_dirty = False
        self._text_dirty = False
        self._syncing = False
        # Buttons' texts of one's own (ribbon.yaml labels:), by objectName.
        self._overrides = {}
        # Buttons' icons of one's own (ribbon.yaml icons:), by objectName.
        self._icon_overrides = {}
        self._dim = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)

        self._views = QTabWidget()
        self._views.addTab(self._visual_view(), _t("Visual"))
        self._views.addTab(self._yaml_view(), _t("YAML"))
        self._views.currentChanged.connect(self._view_changed)

        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.setTextFormat(Qt.TextFormat.RichText)
        # The window's title says whether there are changes, checked once
        # edits rest (writing the tree out on every keystroke lags).
        self._title_timer = QTimer(self)
        self._title_timer.setSingleShot(True)
        self._title_timer.setInterval(300)
        self._title_timer.timeout.connect(self._update_title)
        folder = QPushButton(_t("Open Folder"))
        folder.setToolTip(self._path)
        folder.clicked.connect(self._open_folder)
        reset = QPushButton(_t("Reset to Default"))
        reset.setToolTip(_t("Load the plugin's own ribbon. Save to use it."))
        reset.clicked.connect(self._reset)
        reload_button = QPushButton(_t("Revert"))
        reload_button.setToolTip(_t("Load the saved file again, dropping changes not saved."))
        reload_button.clicked.connect(self._load)
        self._save_button = QPushButton(_t("Save"))
        self._save_button.setDefault(True)
        self._save_button.clicked.connect(self._save)
        close = QPushButton(_t("Close"))
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(folder)
        buttons.addWidget(reset)
        buttons.addWidget(reload_button)
        buttons.addStretch(1)
        buttons.addWidget(self._save_button)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self._views, 1)
        layout.addWidget(self._message)
        layout.addLayout(buttons)
        self._load()

    def _fit_screen(self, parent):
        """At most 1180 x 760, and no more than nine tenths of the screen's
        free width and four fifths of its height (the window's title and the
        taskbar stay clear), centred on it."""
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        free = screen.availableGeometry()
        width = min(1180, int(free.width() * 0.9))
        height = min(760, int(free.height() * 0.8))
        self.resize(width, height)
        self.move(free.x() + (free.width() - width) // 2, free.y() + (free.height() - height) // 2)

    # ---- Building the views -----------------------------------------------

    def _visual_view(self):
        self._tree = _RibbonTree(self._make_entry)
        self._tree.toolbar_of = self._catalog.toolbar_of.get
        self._tree.changed.connect(self._tree_changed)
        self._tree.itemChanged.connect(self._item_changed)
        self._tree.currentItemChanged.connect(self._show_properties)
        self._palette = _Palette()
        self._palette.tree = self._tree
        self._palette.itemDoubleClicked.connect(lambda *_args: self._add_chosen())

        tools = QHBoxLayout()
        moves = QHBoxLayout()
        for row, text, tip, slot in (
                (tools, _t("Add Tab"), "", self._add_tab),
                (tools, _t("Add Group"), "", self._add_group),
                (tools, _t("Add Dropdown"), _t("On a chosen button: turns it into a dropdown"), self._add_dropdown),
                (tools, _t("Add Line"), _t("A line in a dropdown's list"), self._add_line),
                (tools, _t("Remove"), "Delete", self._tree.remove_selected),
                (moves, "▲", _t("Move up"), lambda: self._shift(-1)),
                (moves, "▼", _t("Move down"), lambda: self._shift(1)),
                (moves, _t("Add Caption"), "", lambda: self._add_label(CAPTION)),
                (moves, _t("Add Note"), "", lambda: self._add_label(NOTE)),
                (moves, _t("Expand All"), "", self._tree.expandAll),
                (moves, _t("Collapse All"), "", self._tree.collapseAll)):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
        tools.addStretch(1)
        moves.addStretch(1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(tools)
        left_layout.addLayout(moves)
        left_layout.addWidget(self._tree, 1)
        left_layout.addWidget(self._properties_box())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._search = QLineEdit()
        self._search.setPlaceholderText(_t("Search commands…"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter_palette)
        self._unplaced = QCheckBox(_t("Only commands not on the ribbon"))
        self._unplaced.toggled.connect(self._filter_palette)
        add = QPushButton(_t("Add to Group →"))
        add.clicked.connect(self._add_chosen)
        row = QHBoxLayout()
        row.addWidget(self._unplaced)
        row.addStretch(1)
        row.addWidget(add)
        right_layout.addWidget(self._search)
        right_layout.addLayout(row)
        right_layout.addWidget(self._palette, 1)
        self._fill_palette()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        return splitter

    def _properties_box(self):
        box = QGroupBox(_t("Properties"))
        form = self._form = QFormLayout(box)
        self._title = QLineEdit()
        self._title.textEdited.connect(self._title_edited)
        self._layout = QComboBox()
        for value, text in self.LAYOUTS:
            self._layout.addItem(_t(text), value)
        self._layout.currentIndexChanged.connect(self._layout_changed)
        self._command = QComboBox()
        self._command.setEditable(True)
        self._command.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._command.addItem(_t("(none)"), "")
        for name in sorted(self._catalog.actions, key=lambda n: self._catalog.label(n)[0].lower()):
            self._command.addItem(f"{self._catalog.label(name)[0]}  ({name})", name)
        self._command.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self._command.completer().setCompletionMode(self._command.completer().CompletionMode.PopupCompletion)
        self._command.activated.connect(self._command_changed)
        self._command.lineEdit().editingFinished.connect(self._command_changed)
        self._info = QLabel()
        self._info.setWordWrap(True)
        self._info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(_t("Title"), self._title)
        form.addRow(_t("Button command"), self._command)
        self._inline = QCheckBox(_t("Show its commands in the list"))
        self._inline.toggled.connect(self._inline_toggled)
        form.addRow(_t("Menu"), self._inline)
        self._titled = QCheckBox(_t("Under the menu's name"))
        self._titled.toggled.connect(self._inline_toggled)
        form.addRow("", self._titled)
        self._icon_row = QWidget()
        icon_layout = QHBoxLayout(self._icon_row)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        self._icon_preview = QLabel()
        self._icon_preview.setFixedSize(28, 28)
        choose_icon = QPushButton(_t("Choose…"))
        choose_icon.clicked.connect(self._choose_icon)
        self._reset_icon = QPushButton(_t("Usual Icon"))
        self._reset_icon.clicked.connect(lambda: self._set_icon_override(self._current_key(), None))
        self._icon_note = QLabel()
        icon_layout.addWidget(self._icon_preview)
        icon_layout.addWidget(choose_icon)
        icon_layout.addWidget(self._reset_icon)
        icon_layout.addWidget(self._icon_note, 1)
        form.addRow(_t("Icon"), self._icon_row)
        form.addRow(_t("Buttons"), self._layout)
        form.addRow(self._info)
        self._show_properties(None)
        return box

    def _yaml_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self._text = QPlainTextEdit()
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._text.setFont(font)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._text.setTabChangesFocus(False)
        self._highlighter = _YamlHighlighter(self._text.document(), self._text.palette())
        self._text.textChanged.connect(self._text_changed)
        check = QPushButton(_t("Check"))
        check.clicked.connect(self._check_text)
        self._text_status = QLabel()
        self._text_status.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self._text_status, 1)
        row.addWidget(check)
        layout.addWidget(self._text, 1)
        layout.addLayout(row)
        return widget

    # ---- The palette --------------------------------------------------------

    def _palette_item(self, parent, text, name, entry, icon=None, tip=""):
        item = QTreeWidgetItem(parent, [text, name])
        item.setData(0, ROLE, entry)
        flags = Qt.ItemFlag.ItemIsEnabled
        if entry:
            flags |= Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        item.setFlags(flags)
        if icon is not None and not icon.isNull():
            item.setIcon(0, icon)
        item.setToolTip(0, tip or text)
        item.setToolTip(1, name)
        return item

    def _fill_palette(self):
        catalog = self._catalog
        palette = self._palette
        palette.clear()
        toolbars = QTreeWidgetItem(palette, [_t("Toolbars")])
        toolbars.setFlags(Qt.ItemFlag.ItemIsEnabled)
        bold = toolbars.font(0)
        bold.setBold(True)
        toolbars.setFont(0, bold)
        for name, title, names in sorted(catalog.toolbars, key=lambda t: t[1].lower()):
            node = self._palette_item(
                toolbars, title, name, {"kind": REST, "toolbar": name},
                tip=_t("Drag for all buttons of this toolbar that no group names"))
            for action_name in names:
                label, own = catalog.label(action_name)
                self._palette_item(node, label, action_name, {"kind": CMD, "name": action_name, "toolbar": name},
                                   catalog.icon(action_name), own)
        menus = QTreeWidgetItem(palette, [_t("Menus")])
        menus.setFlags(Qt.ItemFlag.ItemIsEnabled)
        menus.setFont(0, bold)
        for menu in catalog.menus:
            self._palette_menu(menus, menu)
        texts = QTreeWidgetItem(palette, [_t("Texts")])
        texts.setFlags(Qt.ItemFlag.ItemIsEnabled)
        texts.setFont(0, bold)
        for kind, text, tip in (
                (CAPTION, _t("Caption"), _t("A semibold text that is not clicked")),
                (NOTE, _t("Note"), _t("A plain text that is not clicked"))):
            self._palette_item(texts, text, kind, {"kind": kind, "text": text, "for": None}, tip=tip)
        # Texts first: two entries, easily missed under the long lists.
        palette.insertTopLevelItem(0, palette.takeTopLevelItem(palette.indexOfTopLevelItem(texts)))
        texts.setExpanded(True)
        toolbars.setExpanded(True)
        menus.setExpanded(True)

    def _palette_menu(self, parent, menu):
        catalog = self._catalog
        name, title, children = menu
        node = self._palette_item(parent, title, name, {"kind": CMD, "name": name, "toolbar": None},
                                  catalog.icon(name), _t("Drag for a button opening this menu"))
        rest = self._palette_item(node, _t("Everything else in “{menu}”").format(menu=title), name,
                                  {"kind": MENU, "name": name},
                                  tip=_t("The menu's commands that are nowhere else on the ribbon (a “More” group)"))
        italic = rest.font(0)
        italic.setItalic(True)
        rest.setFont(0, italic)
        for child in children:
            if child[1] is None:
                label, own = catalog.label(child[0])
                self._palette_item(node, label, child[0], {"kind": CMD, "name": child[0], "toolbar": None},
                                   catalog.icon(child[0]), own)
            else:
                self._palette_menu(node, child)
        for text, icon in catalog.unnamed.get(name, ()):
            item = self._palette_item(node, text, _t("(no objectName)"), None, icon,
                                      _t("This command has no objectName, so the ribbon cannot place it on "
                                         "its own: drag the menu's “everything else” to show it."))
            item.setForeground(0, QBrush(self._dim))
            item.setData(0, INFO_ROLE, True)

    def _usage(self):
        """{entry key: [where]} of what the tree places, and the names it
        shows through a toolbar's or menu's other buttons."""
        placed = {}
        through = {}
        root = self._tree.invisibleRootItem()
        explicit = self._explicit_toolbar_names()
        for tab in _children(root):
            for group in _children(tab):
                where = f"{tab.text(0)} › {group.text(0)}"
                for item in _children(group):
                    entry = item.data(0, ROLE)
                    if entry["kind"] == CMD:
                        placed.setdefault(entry["name"], []).append(where)
                    elif entry["kind"] == DROP:
                        for name in [entry.get("action")] + [c.data(0, ROLE).get("name") for c in _children(item)]:
                            if not name or name == SEPARATOR:
                                continue
                            menu = item_menu(name)
                            placed.setdefault(menu or name, []).append(where)
                            if menu:
                                placed.setdefault("menu:" + menu, []).append(where)
                                for inner in self._menu_names(menu):
                                    through.setdefault(inner, where)
                    elif entry["kind"] in LABEL_KINDS:
                        continue
                    elif entry["kind"] == REST:
                        placed.setdefault("rest:" + entry["toolbar"], []).append(where)
                        for name in self._toolbar_names(entry["toolbar"]):
                            if name not in explicit.get(entry["toolbar"], set()) | explicit[None]:
                                through.setdefault(name, where)
                    else:
                        placed.setdefault("menu:" + entry["name"], []).append(where)
                        for name in self._menu_names(entry["name"]):
                            through.setdefault(name, where)
        return placed, through

    def _toolbar_names(self, toolbar):
        return next((names for name, _title, names in self._catalog.toolbars if name == toolbar), [])

    def _menu_names(self, menu_name):
        stack = list(self._catalog.menus)
        while stack:
            menu = stack.pop()
            if menu[0] == menu_name:
                return [child[0] for child in menu[2]]
            stack += [c for c in menu[2] if c[1] is not None]
        return []

    def _explicit_toolbar_names(self):
        """{toolbar: names the tree places from it by name}, and under None
        the names dropdowns hold: those a toolbar's "other buttons" leave
        out, as studio_ribbon's _named and _dropdown_names."""
        named = {None: set()}
        iterator = QTreeWidgetItemIterator(self._tree)
        while iterator.value() is not None:
            entry = iterator.value().data(0, ROLE)
            iterator += 1
            if not entry:
                continue
            if entry.get("kind") == CMD and entry.get("toolbar"):
                named.setdefault(entry["toolbar"], set()).add(entry["name"])
            elif entry.get("kind") == DROP and entry.get("action"):
                named[None].add(entry["action"])
            elif entry.get("kind") == LISTED:
                named[None].add(item_menu(entry["name"]) or entry["name"])
        return named

    def _refresh_palette(self):
        placed, through = self._usage()
        iterator = QTreeWidgetItemIterator(self._palette)
        while iterator.value() is not None:
            item = iterator.value()
            iterator += 1
            entry = item.data(0, ROLE)
            if not entry or entry["kind"] in LABEL_KINDS:
                continue
            key = {CMD: entry.get("name"), REST: "rest:" + str(entry.get("toolbar")),
                   MENU: "menu:" + str(entry.get("name"))}[entry["kind"]]
            places = placed.get(key)
            shown_by = through.get(entry.get("name")) if entry["kind"] == CMD else None
            used = bool(places or shown_by)
            item.setData(1, ROLE, used)
            brush = QBrush(self._dim) if used else QBrush()
            item.setForeground(0, brush)
            item.setForeground(1, brush)
            base = item.toolTip(1).split("\n")[0]
            if places:
                base += "\n" + _t("On the ribbon: {where}").format(where="; ".join(places))
            elif shown_by:
                base += "\n" + _t("On the ribbon through another entry: {where}").format(where=shown_by)
            item.setToolTip(1, base)
        self._filter_palette()

    def _filter_palette(self, *_args):
        words = self._search.text().strip().lower().split()
        unplaced = self._unplaced.isChecked()

        def visit(item):
            entry = item.data(0, ROLE)
            text = f"{item.text(0)} {item.text(1)}".lower()
            own = (not words or all(w in text for w in words)) and (not unplaced or not item.data(1, ROLE))
            shown_child = False
            for child in _children(item):
                shown_child = visit(child) or shown_child
            shown = (own and (entry is not None or bool(item.data(0, INFO_ROLE)))) or shown_child
            item.setHidden(not shown)
            if words and shown_child:
                item.setExpanded(True)
            return shown

        for item in _children(self._palette.invisibleRootItem()):
            visit(item)
            item.setHidden(False)

    def _add_chosen(self):
        entries = [i.data(0, ROLE) for i in self._palette.selectedItems() if i.data(0, ROLE)]
        dropdown = self._current_dropdown()
        if dropdown is not None:
            self._tree.add_entries([listed(e) for e in entries if e["kind"] in (CMD, MENU) + LABEL_KINDS],
                                   dropdown)
            return
        group = self._current_group()
        if group is None:
            self._say(_t("Choose a group on the left first."), error=True)
            return
        self._tree.add_entries(entries, group)

    # ---- The tree -----------------------------------------------------------

    @staticmethod
    def _show_ticks(item, group, key):
        """An entry's Large and Labelled ticks, from its group's lists."""
        data = (group.data(0, ROLE) or {}) if group is not None else {}
        for column, name in TICKS.items():
            item.setCheckState(column, Qt.CheckState.Checked if key in data.get(name, ()) else Qt.CheckState.Unchecked)

    def _make_entry(self, entry, group=None):
        """A tree item for `entry` (see tabs_from_data); a dropdown's list
        becomes its children."""
        catalog = self._catalog
        item_names = list(entry.get("items") or ()) if entry["kind"] == DROP else []
        item = QTreeWidgetItem()
        item.setData(0, ROLE, entry)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        if entry["kind"] == CMD:
            name = entry["name"]
            label, own = catalog.label(name)
            if entry.get("toolbar"):
                origin = _t("toolbar “{toolbar}”").format(
                    toolbar=catalog.toolbar_titles.get(entry["toolbar"], entry["toolbar"]))
            elif name in catalog.menu_titles:
                origin = _t("menu button")
            else:
                origin = _t("main window command")
            item.setText(0, self._button_text(name))
            item.setText(1, f"{name} · {origin}")
            item.setToolTip(0, own or name)
            icon = self._button_icon(name)
            if icon is not None and not icon.isNull():
                item.setIcon(0, icon)
            flags |= Qt.ItemFlag.ItemIsUserCheckable
            item.setFlags(flags)
            self._show_ticks(item, group, name)
            found = catalog.found(name)
        elif entry["kind"] == DROP:
            entry = {k: entry.get(k) for k in ("kind", "action", "title")}
            item.setData(0, ROLE, entry)
            flags |= Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDropEnabled
            item.setFlags(flags)
            self._show_dropdown(item)
            key = entry_key(entry)
            self._show_ticks(item, group, key)
            for name in item_names:
                if isinstance(name, dict):
                    kind = next(iter(name))
                    item.addChild(self._make_entry(label_entry(kind, name[kind]), item))
                else:
                    item.addChild(self._make_entry({"kind": LISTED, "name": name}, item))
            item.setExpanded(True)
            found = not entry.get("action") or catalog.found(entry["action"])
        elif entry["kind"] in LABEL_KINDS:
            item.setFlags(flags)
            self._show_label(item)
            found = not entry.get("for") or catalog.found(entry["for"])
        elif entry["kind"] == LISTED:
            name = entry["name"]
            item.setFlags(flags)
            if name == SEPARATOR:
                item.setText(0, "―――――")
                item.setText(1, _t("line"))
                found = True
            elif item_menu(name):
                menu = item_menu(name)
                title = catalog.menu_titles.get(menu) or catalog.label(menu)[0]
                item.setText(0, _t("All of “{menu}”, under its name").format(menu=title) if item_titled(name)
                             else _t("All of “{menu}”").format(menu=title))
                item.setText(1, f"{menu} · {_t('its commands in the list')}")
                item.setToolTip(0, _t("The menu's commands right in this list, between lines, "
                                      "as the menu shows them when the list opens"))
                icon = catalog.icon(menu)
                if icon is not None and not icon.isNull():
                    item.setIcon(0, icon)
                font = item.font(0)
                font.setItalic(True)
                item.setFont(0, font)
                found = catalog.found(menu)
            else:
                _label, own = catalog.label(name)
                item.setText(0, self._button_text(name))
                kind = _t("submenu") if name in catalog.menu_titles else _t("command")
                item.setText(1, f"{name} · {kind}")
                item.setToolTip(0, own or name)
                icon = catalog.icon(name)
                if icon is not None and not icon.isNull():
                    item.setIcon(0, icon)
                found = catalog.found(name)
        elif entry["kind"] == REST:
            toolbar = entry["toolbar"]
            title = catalog.toolbar_titles.get(toolbar, toolbar)
            item.setText(0, _t("All other buttons of “{toolbar}”").format(toolbar=title))
            item.setText(1, f"{toolbar} · {_t('toolbar')}")
            item.setToolTip(0, _t("The toolbar's buttons that no group names, also those plugins add to it"))
            item.setFlags(flags)
            found = toolbar in catalog.toolbar_titles
        else:
            name = entry["name"]
            title = catalog.menu_titles.get(name, name)
            item.setText(0, _t("Everything else in “{menu}”").format(menu=title))
            item.setText(1, f"{name} · {_t('menu')}")
            item.setToolTip(0, _t("The menu's commands that are nowhere else on the ribbon (a “More” group)"))
            item.setFlags(flags)
            found = name in catalog.menu_titles or catalog.found(name)
        font = item.font(0)
        if entry["kind"] in (REST, MENU) + LABEL_KINDS:
            font.setItalic(True)
        if not found:
            font.setItalic(True)
            item.setForeground(0, QBrush(self._dim))
            item.setToolTip(0, _t("Not found in this QGIS session (a plugin not loaded?). Kept as it is."))
        item.setFont(0, font)
        return item

    def _show_dropdown(self, item):
        """A dropdown's row: its title or command, marked as a list."""
        entry = item.data(0, ROLE)
        action = entry.get("action")
        label = entry.get("title") or (self._catalog.label(action)[0] if action else "")
        item.setText(0, f"{label} ▾")
        item.setText(1, f"{action or '—'} · {_t('dropdown')}")
        item.setToolTip(0, _t("A dropdown: its command on its face, its list behind the arrow") if action
                        else _t("A dropdown: a button opening its list"))
        icon = self._button_icon(entry_key(entry)) if entry_key(entry) else None
        item.setIcon(0, icon if icon is not None else QIcon())

    def _label_preview(self, entry):
        """A caption's or note's text as the ribbon will show it."""
        target = entry.get("for")
        title = self._catalog.label(target)[0] if target and self._catalog.found(target) else ""
        return studio_ribbon.label_text(entry.get("text"), title, target)

    def _show_label(self, item):
        """A caption's or note's row: its text as shown, what it is."""
        entry = item.data(0, ROLE)
        word = _t("caption") if entry["kind"] == CAPTION else _t("note")
        item.setText(0, f"“{self._label_preview(entry)}”")
        item.setText(1, f"{word} · {entry.get('for') or '—'}")
        item.setToolTip(0, entry.get("text") or "{title}")

    def _make_container(self, title, data):
        item = QTreeWidgetItem([title])
        item.setData(0, ROLE, data)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
                      | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
        if data["kind"] == "tab":
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
        self._show_translation(item)
        return item

    @staticmethod
    def _show_translation(item):
        """The title as the ribbon shows it (studio_i18n), beside it."""
        title = item.text(0)
        shown = tr(title, "title")
        item.setText(1, f"→ {shown}" if shown != title else "")

    def _fill_data(self, data):
        """Show ribbon.yaml's parsed `data`: its tabs and its labels:."""
        self._overrides = dict(data.get("labels") or {})
        self._icon_overrides = dict(data.get("icons") or {})
        self._fill_tree(tabs_from_data(data))

    def _fill_tree(self, tabs):
        self._syncing = True
        tree = self._tree
        tree.clear()
        for tab in tabs:
            tab_item = self._make_container(tab["title"], {"kind": "tab"})
            tree.addTopLevelItem(tab_item)
            for group in tab["groups"]:
                data = {"kind": "group", "layout": group["layout"], "large": list(group["large"]),
                        "labelled": list(group.get("labelled") or ()), "rows": group["rows"]}
                group_item = self._make_container(group["title"], data)
                tab_item.addChild(group_item)
                for entry in group["entries"]:
                    group_item.addChild(self._make_entry(entry, group_item))
            tab_item.setExpanded(True)
        self._syncing = False
        self._refresh_palette()
        self._show_properties(tree.currentItem())

    def _tabs_of_tree(self):
        """The tree as tabs_from_data gives tabs. A large name stays when its
        group can show it, or when this QGIS does not know it (a plugin's)."""
        tabs = []
        explicit = self._explicit_toolbar_names()
        for tab in _children(self._tree.invisibleRootItem()):
            groups = []
            for group in _children(tab):
                data = group.data(0, ROLE)
                shown = set(self._candidates(group, explicit))
                large = [n for n in data["large"] if n in shown or not self._catalog.found(n)]
                labelled = [n for n in data.get("labelled", ()) if n in shown or not self._catalog.found(n)]
                groups.append({"title": group.text(0).strip(), "layout": data["layout"], "large": large,
                               "labelled": labelled,
                               "rows": data["rows"], "entries": [self._entry_of(c) for c in _children(group)]})
            tabs.append({"title": tab.text(0).strip(), "groups": groups})
        return tabs

    @staticmethod
    def _entry_of(item):
        """A tree entry as tabs_from_data gives it (a dropdown with its list)."""
        entry = dict(item.data(0, ROLE))
        if entry["kind"] == DROP:
            entry["items"] = [label_yaml(c.data(0, ROLE)) if c.data(0, ROLE)["kind"] in LABEL_KINDS
                              else c.data(0, ROLE)["name"] for c in _children(item)]
        return entry

    def _candidates(self, group, explicit=None):
        """The names `group` can show (its commands and its toolbars' other
        buttons), in order."""
        explicit = self._explicit_toolbar_names() if explicit is None else explicit
        names = []
        for child in _children(group):
            entry = child.data(0, ROLE)
            if entry["kind"] in (CMD, DROP):
                if entry_key(entry):
                    names.append(entry_key(entry))
            elif entry["kind"] == REST:
                skip = explicit.get(entry["toolbar"], set()) | explicit.get(None, set())
                names += [n for n in self._toolbar_names(entry["toolbar"]) if n not in skip]
        return list(dict.fromkeys(names))

    def _tree_text(self):
        """ribbon.yaml's text of the tree."""
        data = data_from_tabs(self._tabs_of_tree())
        if self._overrides:
            data["labels"] = dict(self._overrides)
        if self._icon_overrides:
            data["icons"] = dict(self._icon_overrides)
        return dump(data)

    def _all_groups(self):
        return [g for t in _children(self._tree.invisibleRootItem()) for g in _children(t)]

    def _current_group(self):
        item = self._tree.currentItem()
        if item is None:
            return None
        depth = _depth(item)
        if depth == ITEM:
            return item.parent().parent()
        if depth == ENTRY:
            return item.parent()
        if depth == GROUP:
            return item
        return item.child(item.childCount() - 1) if item.childCount() else None

    def _current_dropdown(self):
        """The dropdown chosen, or holding the item chosen; else None."""
        item = self._tree.currentItem()
        if item is not None and _depth(item) == ITEM:
            return item.parent()
        if item is not None and _depth(item) == ENTRY and item.data(0, ROLE)["kind"] == DROP:
            return item
        return None

    def _current_tab(self):
        item = self._tree.currentItem()
        while item is not None and item.parent() is not None:
            item = item.parent()
        return item

    def _unique(self, title, siblings):
        taken = {s.text(0) for s in siblings}
        if title not in taken:
            return title
        number = 2
        while f"{title} {number}" in taken:
            number += 1
        return f"{title} {number}"

    def _add_tab(self):
        root = self._tree.invisibleRootItem()
        current = self._current_tab()
        index = root.indexOfChild(current) + 1 if current is not None else root.childCount()
        item = self._make_container(self._unique("New Tab", _children(root)), {"kind": "tab"})
        root.insertChild(index, item)
        self._tree.setCurrentItem(item)
        self._tree.editItem(item, 0)
        self._tree_changed()

    def _add_group(self):
        tab = self._current_tab()
        if tab is None:
            self._say(_t("Add a tab first."), error=True)
            return
        current = self._current_group()
        index = tab.indexOfChild(current) + 1 if current is not None and current.parent() is tab else tab.childCount()
        data = {"kind": "group", "layout": studio_ribbon.LABELS, "large": [], "labelled": [], "rows": []}
        item = self._make_container(self._unique("New Group", _children(tab)), data)
        tab.insertChild(index, item)
        tab.setExpanded(True)
        self._tree.setCurrentItem(item)
        self._tree.editItem(item, 0)
        self._tree_changed()

    def _add_dropdown(self):
        """A dropdown: the chosen button turned into one (it stays on its
        face, the list goes behind its arrow), else a new one in the chosen
        group."""
        item = self._tree.currentItem()
        if item is not None and _depth(item) == ENTRY and item.data(0, ROLE)["kind"] == CMD:
            group = item.parent()
            index = group.indexOfChild(item)
            entry = {"kind": DROP, "action": item.data(0, ROLE)["name"], "title": None, "items": []}
            self._syncing = True
            group.removeChild(item)
            dropdown = self._make_entry(entry, group)
            group.insertChild(index, dropdown)
            dropdown.setExpanded(True)
            self._syncing = False
        else:
            group = self._current_group()
            if group is None:
                self._say(_t("Choose a group on the left first."), error=True)
                return
            current = item if item is not None and _depth(item) == ENTRY and item.parent() is group else None
            index = group.indexOfChild(current) + 1 if current is not None else group.childCount()
            entry = {"kind": DROP, "action": None, "title": "New Dropdown", "items": []}
            dropdown = self._make_entry(entry, group)
            group.insertChild(index, dropdown)
            group.setExpanded(True)
        self._tree.setCurrentItem(dropdown)
        self._tree_changed()

    def _add_label(self, kind):
        """A caption or note after the chosen item: in a dropdown's list when
        a dropdown or one of its items is chosen, else in the chosen group."""
        entry = {"kind": kind, "text": _t("Caption") if kind == CAPTION else _t("Note"), "for": None}
        item = self._tree.currentItem()
        parent = self._current_dropdown()
        if parent is None:
            parent = self._current_group()
            if parent is None:
                self._say(_t("Choose a group on the left first."), error=True)
                return
        index = parent.indexOfChild(item) + 1 if item is not None and item.parent() is parent else parent.childCount()
        added = self._tree.add_entries([entry], parent, index)
        if added:
            self._tree.setCurrentItem(added[0])
            self._title.setFocus()
            self._title.selectAll()

    def _add_line(self):
        dropdown = self._current_dropdown()
        if dropdown is None:
            self._say(_t("Choose a dropdown or one of its items first."), error=True)
            return
        item = self._tree.currentItem()
        index = dropdown.indexOfChild(item) + 1 if item is not dropdown else dropdown.childCount()
        self._tree.add_entries([{"kind": LISTED, "name": SEPARATOR}], dropdown, index)

    def _shift(self, step):
        _level, items = self._tree._dragged()  # pylint: disable=protected-access
        if not items:
            return
        root = self._tree.invisibleRootItem()
        parent = items[0].parent() or root
        if any((i.parent() or root) is not parent for i in items):
            return
        indexes = [parent.indexOfChild(i) for i in items]
        target = (min(indexes) - 1) if step < 0 else (max(indexes) + 2)
        if target < 0 or target > parent.childCount():
            return
        self._tree.move_items(items, parent, target)

    # ---- Reacting to the tree -------------------------------------------------

    def _tree_changed(self, typing=False):
        """The tree changed. `typing`: a text from the properties, already
        in the tree's row: nothing else (the palette, the properties) depends
        on it."""
        if self._syncing:
            return
        self._tree_dirty = True
        if not typing:
            self._refresh_palette()
            self._show_properties(self._tree.currentItem())
        self._title_timer.start()

    def _item_changed(self, item, column):
        if self._syncing:
            return
        depth = _depth(item)
        if column == 0 and depth in (TAB, GROUP):
            self._syncing = True
            self._show_translation(item)
            self._syncing = False
            if self._tree.currentItem() is item:
                self._set_title(item.text(0), tr(item.text(0), "title"))
            self._tree_changed(typing=True)
            return
        elif column in TICKS and depth == ENTRY and entry_key(item.data(0, ROLE)):
            key = TICKS[column]
            data = item.parent().data(0, ROLE)
            name = entry_key(item.data(0, ROLE))
            names = [n for n in data.get(key, ()) if n != name]
            if item.checkState(column) == Qt.CheckState.Checked:
                names.append(name)
            data[key] = names
            item.parent().setData(0, ROLE, data)
            if self._tree.currentItem() in (item, item.parent()):
                self._show_properties(self._tree.currentItem())
        self._tree_changed()

    def _show_properties(self, item, _previous=None):
        depth = _depth(item) if item is not None else None
        form = self._form
        dropdown = depth == ENTRY and item.data(0, ROLE)["kind"] == DROP
        label = depth in (ENTRY, ITEM) and item.data(0, ROLE)["kind"] in LABEL_KINDS
        button = depth == ENTRY and item.data(0, ROLE)["kind"] == CMD
        listed = depth == ITEM and self._is_renamable(item)
        button = button or listed
        form.labelForField(self._title).setText(_t("Text") if label or button else _t("Title"))
        form.labelForField(self._command).setText(_t("For command") if label else _t("Button command"))
        self._title.setToolTip(_t("{title}: the usual text, {id}: the objectName") if label or button else "")
        for widget, shown in ((self._title, depth in (TAB, GROUP) or dropdown or label or button),
                              (self._command, dropdown or label),
                              (self._icon_row, (button and not listed) or (dropdown and bool(entry_key(item.data(0, ROLE))))),
                              (self._inline, depth == ITEM and self._is_menu_item(item)),
                              (self._titled, depth == ITEM and self._is_menu_item(item)),
                              (self._layout, depth == GROUP)):
            form.setRowVisible(widget, shown)
        self._info.setText("")
        if depth is None:
            return
        if depth in (TAB, GROUP):
            # The name the ribbon shows (its translation) as the hint.
            self._set_title(item.text(0), tr(item.text(0), "title"))
        if depth == TAB:
            return
        if depth == GROUP:
            data = item.data(0, ROLE)
            blocked = self._layout.blockSignals(True)
            self._layout.setCurrentIndex(max(0, self._layout.findData(data["layout"])))
            self._layout.blockSignals(blocked)
            if data["rows"]:
                rows = " | ".join(", ".join(r) for r in data["rows"])
                self._info.setText(_t("Rows (YAML): {rows}").format(rows=rows))
            return
        entry = item.data(0, ROLE)
        if (button and not listed) or dropdown:
            self._show_icon(entry_key(entry))
        if button:
            name = entry["name"]
            self._set_title(self._overrides.get(name, ""), self._catalog.label(name)[0])
            return
        if label:
            self._set_title(entry.get("text") or "", "{title}")
            self._set_command(entry.get("for") or "")
            return
        if dropdown:
            action = entry.get("action")
            self._set_title(entry.get("title") or "", self._catalog.label(action)[0] if action else "")
            self._set_command(action or "")
            return
        if depth == ITEM:
            name = item.data(0, ROLE)["name"]
            for box, value in ((self._inline, bool(item_menu(name))), (self._titled, item_titled(name))):
                blocked = box.blockSignals(True)
                box.setChecked(value)
                box.blockSignals(blocked)
            self._titled.setEnabled(bool(item_menu(name)))

    def _set_title(self, text, hint):
        """The title field's text and placeholder, each set only when it
        differs: setText moves the cursor to the end, also mid-typing."""
        if self._title.text() != text:
            self._title.setText(text)
        if self._title.placeholderText() != hint:
            self._title.setPlaceholderText(hint)

    def _set_command(self, name):
        index = self._command.findData(name) if name else 0
        blocked = self._command.blockSignals(True)
        if index >= 0:
            self._command.setCurrentIndex(index)
        else:
            self._command.setEditText(name)
        self._command.blockSignals(blocked)

    @staticmethod
    def _is_renamable(item):
        """A dropdown list's command or submenu (not a line, nor a menu's
        commands in the list): it takes a text of its own."""
        entry = item.data(0, ROLE) or {}
        name = entry.get("name") or ""
        return entry.get("kind") == LISTED and name != SEPARATOR and not item_menu(name)

    def _is_menu_item(self, item):
        name = item.data(0, ROLE).get("name") or ""
        return bool(item_menu(name)) or name in self._catalog.menu_titles

    def _inline_toggled(self, _checked):
        """A menu in a dropdown's list as a submenu, or its commands (under
        its name or not), as the two switches say."""
        item = self._tree.currentItem()
        if item is None or _depth(item) != ITEM or not self._is_menu_item(item):
            return
        menu = item_menu(item.data(0, ROLE)["name"]) or item.data(0, ROLE)["name"]
        dropdown = item.parent()
        index = dropdown.indexOfChild(item)
        suffix = (TITLED if self._titled.isChecked() else CONTENTS) if self._inline.isChecked() else ""
        replacement = self._make_entry({"kind": LISTED, "name": menu + suffix}, dropdown)
        self._syncing = True
        dropdown.removeChild(item)
        dropdown.insertChild(index, replacement)
        self._syncing = False
        self._tree.setCurrentItem(replacement)
        self._tree_changed()

    def _title_edited(self, text):
        item = self._tree.currentItem()
        if item is not None and _depth(item) in (TAB, GROUP):
            item.setText(0, text)
        elif item is not None and _depth(item) == ENTRY and item.data(0, ROLE)["kind"] == DROP:
            self._change_dropdown(item, title=text.strip() or None)
        elif item is not None and item.data(0, ROLE) and item.data(0, ROLE).get("kind") in LABEL_KINDS:
            self._change_label(item, text=text or None)
        elif item is not None and ((_depth(item) == ENTRY and item.data(0, ROLE)["kind"] == CMD)
                                   or (_depth(item) == ITEM and self._is_renamable(item))):
            self._set_override(item.data(0, ROLE)["name"], text)

    def _button_icon(self, name):
        """A button's icon as the ribbon will show it (its own, if any)."""
        spec = self._icon_overrides.get(name)
        if spec:
            icon = studio_ribbon.icon_from_spec(spec, self._catalog.action)
            if icon is not None:
                return icon
        return self._catalog.icon(name)

    def _current_key(self):
        item = self._tree.currentItem()
        if item is None or _depth(item) != ENTRY:
            return None
        return entry_key(item.data(0, ROLE))

    def _show_icon(self, key):
        if not key:
            return
        icon = self._button_icon(key)
        self._icon_preview.setPixmap(icon.pixmap(24, 24) if icon is not None and not icon.isNull() else QPixmap())
        spec = self._icon_overrides.get(key)
        self._reset_icon.setEnabled(bool(spec))
        self._icon_note.setText(spec or "")
        self._icon_note.setToolTip(spec or "")

    def _choose_icon(self):
        key = self._current_key()
        if not key:
            return
        picker = IconPicker(self._catalog, self)
        if picker.exec() and picker.spec:
            self._set_icon_override(key, picker.spec)

    def _set_icon_override(self, key, spec):
        """Give button `key` an icon of its own (None: its usual one); every
        row of it in the tree follows."""
        if not key or self._icon_overrides.get(key) == spec:
            return
        if spec:
            self._icon_overrides[key] = spec
        else:
            self._icon_overrides.pop(key, None)
        self._syncing = True
        iterator = QTreeWidgetItemIterator(self._tree)
        while iterator.value() is not None:
            item = iterator.value()
            iterator += 1
            entry = item.data(0, ROLE)
            if entry and entry.get("kind") in (CMD, DROP) and _depth(item) == ENTRY and entry_key(entry) == key:
                icon = self._button_icon(key)
                item.setIcon(0, icon if icon is not None else QIcon())
        self._syncing = False
        self._tree_changed()

    def _button_text(self, name):
        """A button's text as the ribbon will show it (its own text, if any)."""
        usual = self._catalog.label(name)[0]
        return studio_ribbon.label_text(self._overrides[name], usual, name) if name in self._overrides else usual

    def _set_override(self, name, text):
        """Give button `name` a text of its own (empty: its usual one); every
        row of it in the tree follows."""
        if text.strip():
            self._overrides[name] = text
        elif name in self._overrides:
            del self._overrides[name]
        else:
            return
        self._syncing = True
        iterator = QTreeWidgetItemIterator(self._tree)
        while iterator.value() is not None:
            entry = iterator.value().data(0, ROLE)
            if entry and entry.get("kind") in (CMD, LISTED) and entry.get("name") == name:
                iterator.value().setText(0, self._button_text(name))
            iterator += 1
        self._syncing = False
        self._tree_changed(typing=True)

    def _change_label(self, item, **changes):
        entry = item.data(0, ROLE)
        entry.update(changes)
        if entry == item.data(0, ROLE):
            return
        self._syncing = True
        item.setData(0, ROLE, entry)
        self._show_label(item)
        self._syncing = False
        self._tree_changed(typing="text" in changes)

    def _command_changed(self, *_args):
        item = self._tree.currentItem()
        if item is None or _depth(item) not in (ENTRY, ITEM):
            return
        kind = item.data(0, ROLE)["kind"]
        if kind != DROP and kind not in LABEL_KINDS:
            return
        text = self._command.currentText().strip()
        index = self._command.findText(text)
        name = self._command.itemData(index) if index >= 0 else text
        if kind == DROP:
            self._change_dropdown(item, action=name or None)
        else:
            self._change_label(item, **{"for": name or None})

    def _change_dropdown(self, item, **changes):
        """Set a dropdown's action or title; its Large tick follows its key."""
        entry = item.data(0, ROLE)
        old = entry_key(entry)
        entry.update(changes)
        if entry == item.data(0, ROLE):
            return
        new = entry_key(entry)
        group = item.parent()
        data = group.data(0, ROLE)
        if new != old and any(old in data.get(k, ()) for k in TICKS.values()):
            for k in TICKS.values():
                if old in data.get(k, ()):
                    data[k] = [new if n == old else n for n in data[k] if n != new]
            group.setData(0, ROLE, data)
        self._syncing = True
        item.setData(0, ROLE, entry)
        self._show_dropdown(item)
        self._syncing = False
        self._tree_changed(typing="title" in changes)

    def _layout_changed(self, _index):
        item = self._tree.currentItem()
        if item is None or _depth(item) != GROUP:
            return
        data = item.data(0, ROLE)
        data["layout"] = self._layout.currentData()
        item.setData(0, ROLE, data)
        self._tree_changed()

    # ---- The text -------------------------------------------------------------

    def _text_changed(self):
        if self._syncing:
            return
        self._text_dirty = True
        self._text_status.setText("")
        self._update_title()

    def _set_text(self, text):
        self._syncing = True
        self._text.setPlainText(text)
        self._syncing = False

    def _check_text(self):
        problem = check_text(self._text.toPlainText())
        self._show_problem(problem)
        return problem is None

    def _show_problem(self, problem):
        if problem is None:
            self._text_status.setText(f"<span style='color:#3b9d3b'>✔ {_t('The file reads.')}</span>")
            return
        message, line = problem
        self._text_status.setText(f"<span style='color:#d04040'>✖ {_html(message)}</span>")
        if line is not None:
            block = self._text.document().findBlockByNumber(line)
            cursor = QTextCursor(block)
            self._text.setTextCursor(cursor)
            self._text.centerCursor()

    def _view_changed(self, index):
        if index == 1 and self._tree_dirty:
            self._set_text(self._tree_text())
            self._tree_dirty = False
            self._text_dirty = False
            self._text_status.setText("")
        elif index == 0 and self._text_dirty:
            text = self._text.toPlainText()
            problem = check_text(text)
            if problem is not None:
                blocked = self._views.blockSignals(True)
                self._views.setCurrentIndex(1)
                self._views.blockSignals(blocked)
                self._show_problem(problem)
                self._say(_t("Fix the YAML first: the visual view needs a file that reads."), error=True)
                return
            self._fill_data(yaml.safe_load(text))
            self._text_dirty = False
            self._tree_dirty = False
        self._update_title()

    # ---- Loading and saving ---------------------------------------------------

    def _current_text(self):
        """The file as the views now hold it."""
        if self._tree_dirty:
            return self._tree_text()
        return self._text.toPlainText()

    def _modified(self):
        """Whether the views differ from the file saved, by content (a
        file and the visual view's rewrite of it are the same ribbon)."""
        text = self._current_text()
        if text == self._saved:
            return False
        try:
            return yaml.safe_load(text) != yaml.safe_load(self._saved)
        except yaml.YAMLError:
            return True

    def _update_title(self):
        title = _t("Ribbon Editor")
        if self._modified():
            title += " *"
        self.setWindowTitle(title)

    def _load(self, *_args, path=None):
        """Open the profile's ribbon.yaml (or the plugin's when there is none,
        or `path`)."""
        if path is None:
            path = self._path if os.path.exists(self._path) else studio_ribbon.TABS_FILE
        try:
            with open(path, encoding="utf-8") as stream:
                text = stream.read()
        except OSError as error:
            self._say(_t("Could not read {path}: {error}").format(path=path, error=error), error=True)
            return
        self._set_text(text)
        # The plugin's file loaded over the profile's (Reset to Default) is
        # a change not saved yet.
        if path == self._path or not os.path.exists(self._path):
            self._saved = text
        self._tree_dirty = False
        problem = check_text(text)
        if problem is None:
            self._fill_data(yaml.safe_load(text))
            self._text_dirty = False
            blocked = self._views.blockSignals(True)
            self._views.setCurrentIndex(0)
            self._views.blockSignals(blocked)
            if studio_ribbon.TABS_ERROR and path == self._path:
                self._say(_t("The default ribbon is shown: this file did not read when QGIS started."), error=True)
            else:
                self._say("")
        else:
            with open(studio_ribbon.TABS_FILE, encoding="utf-8") as stream:
                self._fill_data(yaml.safe_load(stream))
            self._text_dirty = True
            blocked = self._views.blockSignals(True)
            self._views.setCurrentIndex(1)
            self._views.blockSignals(blocked)
            self._show_problem(problem)
            self._say(_t("This file does not read, so the default ribbon is shown. Fix it in the YAML view."),
                      error=True)
        self._update_title()

    def _reset(self):
        self._load(path=studio_ribbon.TABS_FILE)
        self._say(_t("The plugin's own ribbon is loaded. Save to use it."))

    def _save(self):
        if self._views.currentIndex() == 1 or not self._tree_dirty:
            text = self._text.toPlainText()
        else:
            text = self._tree_text()
        problem = check_text(text)
        if problem is not None:
            self._views.setCurrentIndex(1)
            if self._tree_dirty:
                self._set_text(text)
            self._show_problem(problem)
            self._say(_t("Not saved: the file does not read."), error=True)
            return False
        try:
            with open(studio_ribbon.TABS_FILE, encoding="utf-8") as stream:
                default = stream.read()
        except OSError:
            default = None
        try:
            if text == default:
                # The plugin's own: later versions of it reach this profile.
                if os.path.exists(self._path):
                    os.remove(self._path)
            else:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                temporary = self._path + ".tmp"
                with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(text)
                os.replace(temporary, self._path)
        except OSError as error:
            self._say(_t("Could not save {path}: {error}").format(path=self._path, error=error), error=True)
            return False
        self._saved = text
        if self._views.currentIndex() == 0:
            # Saved from the tree: the text is that file now.
            if self._tree_dirty:
                self._set_text(text)
            self._text_dirty = False
        self._tree_dirty = False
        self.saved.emit()
        if studio_ribbon.TABS_ERROR:
            self._say(_t("Saved, but the ribbon could not read it: {error}").format(
                error=studio_ribbon.TABS_ERROR), error=True)
        else:
            self._say("")
        self._update_title()
        return True

    def _open_folder(self):
        """The folder of the profile's ribbon.yaml, the file chosen when it
        exists (Windows Explorer), else just the folder."""
        folder = os.path.dirname(self._path)
        os.makedirs(folder, exist_ok=True)
        if os.name == "nt" and os.path.exists(self._path):
            QProcess.startDetached("explorer", ["/select,", os.path.normpath(self._path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _say(self, text, error=False):
        color = "#d04040" if error else self.palette().color(QPalette.ColorRole.WindowText).name()
        self._message.setText(f"<span style='color:{color}'>{_html(text)}</span>" if text else "")
        self._message.setVisible(bool(text))

    def reject(self):  # pylint: disable=invalid-name
        """Close (the button, Escape, the window's close): asks first when
        there are changes not saved."""
        if self._modified():
            answer = QMessageBox.question(
                self, _t("Ribbon Editor"), _t("Save the changes to the ribbon?"),
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
            if answer == QMessageBox.StandardButton.Cancel or (
                    answer == QMessageBox.StandardButton.Save and not self._save()):
                return
        super().reject()


def _html(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
