"""The startup splash screen in the Studio theme's colours.

QGIS 4 draws its splash before plugins load, from the folder the profile's
customization file names (QGIS/QGISCUSTOMIZATION.xml, root element
`Customization`, attributes `enabled` and `splashPath`; main.cpp reads
`splashPath + "splash.png"`). QgsApplication.splashPath() itself always
returns the built-in ":/images/splash/". So the plugin draws splash.png
for the active theme into the profile and points the customization file at
it: the next start shows it.

The file is shared with Settings > Interface Customization, so only the
two attributes are touched, and only when that is safe:
- no file: created with nothing else in it (unless a QGIS 3 .ini is
  beside it, which QGIS imports while the XML is missing);
- customization off with customizations in it: left alone (turning it on
  would apply them);
- a splashPath of the user's own: left alone.
What the plugin turned on it turns off again (SPLASH_OWNED_SETTING).

A picture of one's own for a theme: `<profile>/studio_themes/splash/<theme
folder>.png` (leaf.png, premium.png, ...) is used instead of drawing.
Nothing is redrawn or rewritten when it is already in place.
"""

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsSettings
from qgis.PyQt.QtCore import QRectF, QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPixmap

from .studio_tokens import is_dark

SPLASH_SETTING = "studio_themes/themeSplash"
# "created": the plugin wrote the file; "enabled": it switched customization on.
SPLASH_OWNED_SETTING = "studio_themes/themeSplashOwned"
# Which picture splash.png holds now (see _write_image).
SPLASH_STAMP_SETTING = "studio_themes/themeSplashStamp"
# Raise when draw() changes, so drawn splashes are redrawn once.
DRAW_VERSION = 4
BUILTIN = ":/images/splash/splash.png"
DEFAULT_SIZE = QSize(1977, 946)
FONT = "Inter"


def _settings_dir():
    return Path(QgsApplication.qgisSettingsDirPath())


def customization_file():
    return _settings_dir() / "QGIS" / "QGISCUSTOMIZATION.xml"


def splash_dir():
    return _settings_dir() / "studio_themes" / "splash"


def _ours(path):
    return Path(path).resolve() == splash_dir().resolve() if path else False


def _log(text):
    QgsMessageLog.logMessage(text, "QGIS Studio Themes", Qgis.MessageLevel.Info)


def enabled():
    return QgsSettings().value(SPLASH_SETTING, False, type=bool)


def set_enabled(value):
    QgsSettings().setValue(SPLASH_SETTING, bool(value))


def _color(tokens, name, fallback):
    color = QColor(str(tokens.get(name, fallback)))
    return color if color.isValid() else QColor(fallback)


def draw(tokens, theme_name):
    """The splash image: the theme's window colour, QGIS's logo, version
    and release name, the theme's name; a dark band at the bottom, where
    QGIS writes its loading messages in a light colour."""
    builtin = QPixmap(BUILTIN)
    size = builtin.size() if not builtin.isNull() else DEFAULT_SIZE
    w, h = size.width(), size.height()
    bg = _color(tokens, "@bg_window", "#FFFFFF")
    dark = is_dark(bg.name())
    text = _color(tokens, "@text_bright" if dark else "@text", "#202020")
    dim = _color(tokens, "@text_dim", "#707070")
    accent = _color(tokens, "@accent", "#589632")
    band_color = QColor(_color(tokens, "@bg_statusbar" if dark else "@accent_pressed", "#202020"))
    if band_color.lightnessF() > 0.35:
        band_color = band_color.darker(220)

    image = QImage(w, h, QImage.Format.Format_RGB32)
    image.fill(bg)
    p = QPainter(image)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                     | QPainter.RenderHint.SmoothPixmapTransform)
    band = int(h * 0.08)
    p.fillRect(0, h - band, w, band, band_color)
    p.fillRect(0, h - band - int(h * 0.008), w, int(h * 0.008), accent)

    margin = int(w * 0.07)
    logo_size = int(h * 0.34)
    top = int(h * 0.20)
    logo = QGuiApplication.windowIcon().pixmap(QSize(logo_size, logo_size))
    if not logo.isNull():
        p.drawPixmap(margin, top, logo_size, logo_size, logo)
    x = margin + logo_size + int(w * 0.035)

    def font(px, weight):
        f = QFont(FONT)
        f.setPixelSize(int(px))
        f.setWeight(weight)
        return f

    version = ".".join(Qgis.version().split("-")[0].split(".")[:2])
    p.setFont(font(h * 0.20, QFont.Weight.DemiBold))
    p.setPen(text)
    p.drawText(QRectF(x, top - h * 0.03, w - x - margin, h * 0.24),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"QGIS {version}")
    p.setFont(font(h * 0.085, QFont.Weight.DemiBold))
    p.setPen(accent if not dark else _color(tokens, "@icon_accent", accent.name()))
    p.drawText(QRectF(x, top + h * 0.21, w - x - margin, h * 0.12),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, Qgis.releaseName())
    p.setFont(font(h * 0.04, QFont.Weight.Normal))
    p.setPen(dim)
    p.drawText(QRectF(margin, h - band - h * 0.13, w - 2 * margin, h * 0.08),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               f"Studio {theme_name}  ·  an OSGeo project")
    p.end()
    # QGIS writes its loading messages in the inverse of the pixel at
    # (width / 2, height - 8) (qgisapp.cpp, splashTextColor): black there
    # makes them white. The pixel sits under the centred text.
    image.setPixelColor(w // 2, h - 8, QColor(0, 0, 0))
    return image


def _read():
    """(tree, root) of the customization file, (None, None) without one."""
    path = customization_file()
    if not path.exists():
        return None, None
    tree = ET.parse(path)
    return tree, tree.getroot()


def _write_image(folder, tokens, theme_name, theme_folder):
    """splash.png for the theme: the user's own `<theme folder>.png` beside
    it (e.g. leaf.png) copied, else drawn. Skipped when splash.png already
    holds the same thing (SPLASH_STAMP_SETTING: source, QGIS version,
    DRAW_VERSION or the own file's size and time)."""
    target = folder / "splash.png"
    own = folder / f"{theme_folder}.png"
    if own.is_file():
        info = own.stat()
        stamp = f"own|{own.name}|{info.st_size}|{info.st_mtime_ns}"
    else:
        stamp = f"drawn|{theme_folder}|{Qgis.version()}|{DRAW_VERSION}"
    settings = QgsSettings()
    if target.is_file() and settings.value(SPLASH_STAMP_SETTING, "", type=str) == stamp:
        return True
    if own.is_file():
        shutil.copyfile(own, target)
    elif not draw(tokens, theme_name).save(str(target), "PNG"):
        return False
    settings.setValue(SPLASH_STAMP_SETTING, stamp)
    return True


def apply(tokens, theme_name, theme_folder):
    """Put the theme's splash in place and point the customization file
    at it. Returns False when the file was left alone (see the module
    notes)."""
    try:
        path = customization_file()
        tree, root = _read()
        owned = QgsSettings().value(SPLASH_OWNED_SETTING, "", type=str)
        if root is None:
            if (path.parent / "QGISCUSTOMIZATION3.ini").exists():
                _log("Theme splash: a QGIS 3 customization file is waiting to be imported; not changed.")
                return False
            root = ET.Element("Customization")
            tree = ET.ElementTree(root)
            owned = "created"
        else:
            current = root.get("splashPath")
            # A splash of the user's own is kept; a path with no
            # splash.png in it (QGIS then shows a small empty box) is not.
            if current and not _ours(current) and (Path(current) / "splash.png").is_file():
                _log(f"Theme splash: the customization file already names a splash ({current}); not changed.")
                return False
            if root.get("enabled") != "true":
                if len(root):
                    _log("Theme splash: interface customization is off; turning it on would apply it. Not changed.")
                    return False
                owned = owned or "enabled"
        folder = splash_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if not _write_image(folder, tokens, theme_name, theme_folder):
            return False
        splash_path = folder.as_posix() + "/"
        if not path.exists() or root.get("enabled") != "true" or root.get("splashPath") != splash_path:
            root.set("enabled", "true")
            root.set("splashPath", splash_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tree.write(path, encoding="UTF-8", xml_declaration=True)
        QgsSettings().setValue(SPLASH_OWNED_SETTING, owned)
        return True
    except (OSError, ET.ParseError) as error:
        _log(f"Theme splash: {error}")
        return False


def restore():
    """Back to QGIS's own splash: our splashPath removed, and what the
    plugin turned on (or the file it created) undone."""
    try:
        settings = QgsSettings()
        owned = settings.value(SPLASH_OWNED_SETTING, "", type=str)
        tree, root = _read()
        if root is not None and _ours(root.get("splashPath")):
            del root.attrib["splashPath"]
            path = customization_file()
            if owned == "created" and not len(root) and set(root.attrib) <= {"enabled"}:
                path.unlink()
            else:
                if owned and not len(root):
                    root.set("enabled", "false")
                tree.write(path, encoding="UTF-8", xml_declaration=True)
        settings.remove(SPLASH_OWNED_SETTING)
    except (OSError, ET.ParseError) as error:
        _log(f"Theme splash: {error}")
