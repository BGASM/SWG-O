"""
SWG-O - live picture-in-picture tiles for SWG Restoration clients.

Author: Beargasm

One small always-on-top window per client. The picture is a magnifying lens
over the live client: scroll to zoom, right-drag to pan the lens around.

Requires PySide6:
    pip install PySide6

Run:
    py .\\swgo.py

Controls, over the picture:
    wheel               zoom the lens in / out (1x to 8x)
    ctrl + wheel        resize the tile window
    right-drag          pan the lens (only does anything when zoomed in)
    right-click         context menu (no drag)
    left-click          bring that client to the foreground
    middle-click        reset lens to full frame
    double-click        reset lens to full frame

Controls, on the chrome:
    drag title strip    move the tile
    drag corner grip    resize the tile

Auto-hide (on by default, toggle in the menu): a tile hides itself while its
own client is the foreground window, since you are already looking at it.
Focus the other client and only the first tile shows. Alt-tab to a browser or
a spreadsheet and both come back.

Geometry, zoom and lens position persist to %APPDATA%\\SWG-O\\swgo.json.

Notes that matter:
  - Clients must be borderless windowed. Exclusive fullscreen bypasses the
    compositor and the tile renders black.
  - Never minimize a client. DWM stops updating a minimized source and the
    tile freezes. Move it off-screen instead.
  - DWM composites the thumbnail OVER this window's own painting, so all
    chrome lives in the margins around the picture, never on top of it.
"""

import ctypes
import json
import os
import sys
from ctypes import wintypes
from datetime import datetime

if sys.platform != "win32":
    sys.exit("Windows only.")

# DPI awareness is deliberately NOT set here. Qt6 sets
# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 during QApplication construction,
# which is stricter and better than anything we would set by hand. Calling
# SetProcessDpiAwareness() first only makes Qt's call fail with "Access is
# denied" and leaves the process on the weaker v1 context. Nothing runs before
# QApplication that needs DPI-correct coordinates.

import signal

from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor, QFont, QAction, QIcon, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget, QMenu

# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

APP_NAME = "SWG-O"
APP_AUTHOR = "Beargasm"
APP_VERSION = "1.0.0"

# Default window class of the game client. Overridable from the config file so
# a different server or client build does not require editing code. If the
# tiles come up empty, run tools\swg_pids.py to find the right CLASS value.
DEFAULT_CLIENT_CLASS = "SWG Restoration"

# Config lives in %APPDATA%, not next to the exe: an installed copy may sit in
# Program Files, which is not writable by a normal user.
def _config_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "SWG-O")
    try:
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "swgo.json")
    except OSError:
        # Last resort: beside the script. Fine when running from source.
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "swgo.json")


CONFIG_PATH = _config_path()

# Icon, when running from a PyInstaller bundle or from source next to the file.
def _asset(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


UI_FONT = "Segoe UI"

BAR_H = 20        # title strip height
SIDE = 4          # left/right margin
BOT_H = 14        # bottom strip, holds the resize grip
GRIP = 14

MIN_W = 200        # absolute floor
MAX_W = 1600       # ceiling; the real cap is the user's screen width, see Tile.max_width

MIN_ZOOM, MAX_ZOOM = 1.0, 8.0
ZOOM_STEP = 1.15          # per wheel notch
DRAG_SLOP = 4             # px of right-drag before it counts as a pan, not a click

FOCUS_POLL_MS = 150       # how often to check which window is foreground
RESCAN_MS = 3000          # how often to look for clients appearing or dying

# --------------------------------------------------------------------------
# win32 / dwm
# --------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

GW_OWNER = 4
SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

DWM_TNP_RECTDESTINATION = 0x01
DWM_TNP_RECTSOURCE = 0x02
DWM_TNP_OPACITY = 0x04
DWM_TNP_VISIBLE = 0x08
DWM_TNP_SOURCECLIENTAREAONLY = 0x10


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class DWM_THUMBNAIL_PROPERTIES(ctypes.Structure):
    _fields_ = [
        ("dwFlags", wintypes.DWORD),
        ("rcDestination", RECT),
        ("rcSource", RECT),
        ("opacity", ctypes.c_ubyte),
        ("fVisible", wintypes.BOOL),
        ("fSourceClientAreaOnly", wintypes.BOOL),
    ]


HTHUMBNAIL = ctypes.c_void_p
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

dwmapi.DwmRegisterThumbnail.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.POINTER(HTHUMBNAIL)]
dwmapi.DwmRegisterThumbnail.restype = ctypes.HRESULT
dwmapi.DwmUnregisterThumbnail.argtypes = [HTHUMBNAIL]
dwmapi.DwmUnregisterThumbnail.restype = ctypes.HRESULT
dwmapi.DwmUpdateThumbnailProperties.argtypes = [HTHUMBNAIL, ctypes.POINTER(DWM_THUMBNAIL_PROPERTIES)]
dwmapi.DwmUpdateThumbnailProperties.restype = ctypes.HRESULT
dwmapi.DwmQueryThumbnailSourceSize.argtypes = [HTHUMBNAIL, ctypes.POINTER(SIZE)]
dwmapi.DwmQueryThumbnailSourceSize.restype = ctypes.HRESULT

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FILETIME)] * 4
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def class_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def pid_of(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def start_time(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        if not kernel32.GetProcessTimes(h, *(ctypes.byref(x) for x in (c, e, k, u))):
            return None
        ticks = (c.dwHighDateTime << 32) | c.dwLowDateTime
        return datetime.fromtimestamp((ticks - 116444736000000000) / 10_000_000)
    finally:
        kernel32.CloseHandle(h)


def find_clients():
    """Return client hwnds ordered by process start time, oldest first."""
    target = CONFIG.get("client_class") or DEFAULT_CLIENT_CLASS
    found = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        if class_of(hwnd) != target:
            return True
        pid = pid_of(hwnd)
        found.append((hwnd, pid, start_time(pid)))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    found.sort(key=lambda r: (r[2] or datetime.max, r[1]))
    return found


def focus_window(hwnd):
    """SetForegroundWindow is blocked unless we own the foreground; attach first."""
    if not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return True
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    my_tid = kernel32.GetCurrentThreadId()
    attached = False
    if fg_tid and fg_tid != my_tid:
        attached = bool(user32.AttachThreadInput(my_tid, fg_tid, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(my_tid, fg_tid, False)
    return True


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


# --------------------------------------------------------------------------
# tile
# --------------------------------------------------------------------------

class Tile(QWidget):
    """
    The picture is a lens over the source window.

    Lens state lives in cfg as three numbers:
        zoom  1.0 = whole window, 4.0 = a quarter of it in each axis
        cx    lens centre, fraction of source width
        cy    lens centre, fraction of source height

    The lens always keeps the source aspect ratio, so zooming never reshapes
    the tile. Only the source's own aspect does.
    """

    def __init__(self, slot, cfg):
        super().__init__()
        self.slot = slot
        self.cfg = cfg
        self.src_hwnd = None
        self.thumb = None
        # Placeholder aspect until a client attaches and reports its real size.
        # Derived from the primary screen so a 16:10 or 21:9 user does not see
        # a 16:9 "waiting for client" box that then jumps shape.
        self.src_size = (2560, 1440)
        scr = QGuiApplication.primaryScreen()
        if scr:
            g = scr.geometry()
            if g.width() > 0 and g.height() > 0:
                self.src_size = (g.width(), g.height())

        self._drag_off = None
        self._resizing = False
        self._resize_origin = None
        self._pan_from = None
        self._pan_moved = False

        cfg.setdefault("zoom", 1.0)
        cfg.setdefault("cx", 0.5)
        cfg.setdefault("cy", 0.5)
        cfg.setdefault("opacity", 255)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setContextMenuPolicy(Qt.PreventContextMenu)  # we drive the menu by hand
        self.setMouseTracking(True)
        self.setMinimumWidth(MIN_W)
        # Auto-hide re-shows tiles constantly. Without this, every show() would
        # yank focus away from whatever you were typing in.
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        w = int(cfg.get("w", self.default_width()))
        self.resize(w, self._height_for(w))
        prim = self.primary_rect()
        self.move(int(cfg.get("x", prim.left() + 60 + slot * (w + 20))),
                  int(cfg.get("y", prim.top() + 60)))
        self.clamp_to_desktop()

    # -- screen fitting ---------------------------------------------------

    @staticmethod
    def primary_rect():
        scr = QGuiApplication.primaryScreen()
        return scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)

    @staticmethod
    def desktop_rect():
        """Union of every screen's usable area. The virtual desktop."""
        r = QRect()
        for s in QGuiApplication.screens():
            r = r.united(s.availableGeometry())
        return r if not r.isNull() else QRect(0, 0, 1920, 1080)

    def default_width(self):
        """A quarter of the primary screen, bounded. 480 on 1920, 340 on 1366."""
        return int(clamp(self.primary_rect().width() * 0.25, MIN_W, 640))

    def max_width(self):
        """Never wider than the screen it is on, whatever MAX_W says."""
        return int(clamp(self.desktop_rect().width() - 40, MIN_W, MAX_W))

    def clamp_to_desktop(self):
        """
        Keep the tile reachable.

        A config written on a three-monitor rig will place tiles at
        coordinates that do not exist on a laptop, leaving an invisible
        window with no way to drag it back. Shrink to fit, then pull the
        title strip back onto a real screen if it has ended up nowhere.
        """
        if self.width() > self.max_width():
            self.set_width(self.max_width())

        bar = QRect(self.x(), self.y(), self.width(), BAR_H)
        for s in QGuiApplication.screens():
            if s.availableGeometry().intersected(bar).width() >= 80:
                return   # enough of the drag handle is visible

        prim = self.primary_rect()
        self.move(prim.left() + 60 + self.slot * (self.width() + 20),
                  prim.top() + 60)

    # -- geometry ---------------------------------------------------------

    def _aspect(self):
        sw, sh = self.src_size
        return sh / sw if sw else 9 / 16

    def _height_for(self, w):
        inner = max(1, w - 2 * SIDE)
        return BAR_H + int(round(inner * self._aspect())) + BOT_H

    def picture_rect(self):
        return QRect(SIDE, BAR_H, self.width() - 2 * SIDE, self.height() - BAR_H - BOT_H)

    def grip_rect(self):
        return QRect(self.width() - GRIP, self.height() - GRIP, GRIP, GRIP)

    # -- the lens ---------------------------------------------------------

    def lens_px(self):
        """Lens rect in source pixels as (x, y, w, h), clamped inside the source."""
        sw, sh = self.src_size
        z = clamp(float(self.cfg["zoom"]), MIN_ZOOM, MAX_ZOOM)
        lw = sw / z
        lh = sh / z
        lx = clamp(self.cfg["cx"] * sw - lw / 2, 0.0, sw - lw)
        ly = clamp(self.cfg["cy"] * sh - lh / 2, 0.0, sh - lh)
        return lx, ly, lw, lh

    def set_lens_origin(self, lx, ly):
        """Store a top-left lens position back as a clamped centre fraction."""
        sw, sh = self.src_size
        _, _, lw, lh = self.lens_px()
        lx = clamp(lx, 0.0, sw - lw)
        ly = clamp(ly, 0.0, sh - lh)
        self.cfg["cx"] = (lx + lw / 2) / sw
        self.cfg["cy"] = (ly + lh / 2) / sh

    def zoom_at(self, notches, anchor):
        """
        Zoom about a point, so whatever pixel sits under the cursor stays put.

        anchor is in tile coordinates. Convert it to a source pixel using the
        current lens, apply the new zoom, then re-derive the lens origin so the
        same source pixel lands back under the cursor.
        """
        pic = self.picture_rect()
        if pic.width() <= 0 or pic.height() <= 0:
            return
        u = clamp((anchor.x() - pic.left()) / pic.width(), 0.0, 1.0)
        v = clamp((anchor.y() - pic.top()) / pic.height(), 0.0, 1.0)

        lx, ly, lw, lh = self.lens_px()
        sx = lx + u * lw
        sy = ly + v * lh

        old = clamp(float(self.cfg["zoom"]), MIN_ZOOM, MAX_ZOOM)
        new = clamp(old * (ZOOM_STEP ** notches), MIN_ZOOM, MAX_ZOOM)
        if abs(new - old) < 1e-6:
            return
        self.cfg["zoom"] = new

        sw, sh = self.src_size
        nlw, nlh = sw / new, sh / new
        self.set_lens_origin(sx - u * nlw, sy - v * nlh)
        self.push()
        self.update()

    def pan(self, dx_tile, dy_tile):
        """Drag the picture: content follows the cursor, so the lens moves opposite."""
        pic = self.picture_rect()
        if pic.width() <= 0 or pic.height() <= 0:
            return
        lx, ly, lw, lh = self.lens_px()
        self.set_lens_origin(lx - dx_tile * (lw / pic.width()),
                             ly - dy_tile * (lh / pic.height()))
        self.push()
        self.update()

    def reset_lens(self):
        self.cfg.update({"zoom": 1.0, "cx": 0.5, "cy": 0.5})
        self.push()
        self.update()
        self.save()

    def set_zoom(self, z):
        self.cfg["zoom"] = clamp(float(z), MIN_ZOOM, MAX_ZOOM)
        self.push()
        self.update()
        self.save()

    # -- thumbnail --------------------------------------------------------

    def attach(self, hwnd):
        if self.thumb:
            self.detach()
        self.src_hwnd = hwnd
        th = HTHUMBNAIL()
        if dwmapi.DwmRegisterThumbnail(int(self.winId()), hwnd, ctypes.byref(th)) != 0:
            self.src_hwnd = None
            return False
        self.thumb = th
        size = SIZE()
        if dwmapi.DwmQueryThumbnailSourceSize(th, ctypes.byref(size)) == 0:
            if size.cx > 0 and size.cy > 0:
                self.src_size = (size.cx, size.cy)
        self.resize(self.width(), self._height_for(self.width()))
        self.push()
        return True

    def detach(self):
        if self.thumb:
            dwmapi.DwmUnregisterThumbnail(self.thumb)
            self.thumb = None
        self.src_hwnd = None
        self.update()

    def push(self):
        """Send destination rect, lens rect and opacity to DWM."""
        if not self.thumb:
            return
        p = DWM_THUMBNAIL_PROPERTIES()
        p.dwFlags = (DWM_TNP_RECTDESTINATION | DWM_TNP_OPACITY
                     | DWM_TNP_VISIBLE | DWM_TNP_SOURCECLIENTAREAONLY)

        # Qt widget coordinates are logical pixels; DWM wants physical ones.
        # Identical at 100% scaling, but at 150% an unscaled rect would leave
        # the picture filling only two thirds of the tile.
        r = self.picture_rect()
        dpr = self.devicePixelRatioF() or 1.0
        p.rcDestination = RECT(int(r.left() * dpr), int(r.top() * dpr),
                               int((r.right() + 1) * dpr), int((r.bottom() + 1) * dpr))
        p.opacity = int(self.cfg.get("opacity", 255))
        p.fVisible = True
        p.fSourceClientAreaOnly = True

        if float(self.cfg["zoom"]) > 1.001:
            lx, ly, lw, lh = self.lens_px()
            p.rcSource = RECT(int(lx), int(ly), int(lx + lw), int(ly + lh))
            p.dwFlags |= DWM_TNP_RECTSOURCE

        dwmapi.DwmUpdateThumbnailProperties(self.thumb, ctypes.byref(p))

    def alive(self):
        return bool(self.src_hwnd and user32.IsWindow(self.src_hwnd))

    # -- auto-hide --------------------------------------------------------

    def apply_visibility(self, fg_hwnd):
        """
        Hide this tile while its own client is foreground.

        Only one window is foreground at a time, so at most one tile is ever
        hidden. Anything that is not one of the clients (a browser, an editor,
        our own context menu) leaves both showing.
        """
        if not CONFIG.get("auto_hide", True):
            if not self.isVisible():
                self.show()
                self.push()
            return

        hide = bool(self.src_hwnd) and int(fg_hwnd or 0) == int(self.src_hwnd)
        if hide:
            if self.isVisible():
                self.hide()
        elif not self.isVisible():
            self.show()
            self.push()   # re-assert the destination rect after a show

    # -- painting ---------------------------------------------------------

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.fillRect(self.rect(), QColor(18, 20, 24))
        qp.setPen(QColor(70, 80, 95))
        qp.drawRect(0, 0, self.width() - 1, self.height() - 1)

        f = QFont(UI_FONT)
        f.setPointSize(8)
        qp.setFont(f)

        qp.setPen(QColor(190, 200, 215))
        label = self.cfg.get("label") or f"Client {self.slot + 1}"
        state = "" if self.alive() else "  [no client]"
        qp.drawText(QRect(SIDE + 2, 0, self.width() - 2 * SIDE - 46, BAR_H),
                    Qt.AlignVCenter | Qt.AlignLeft, label + state)

        z = float(self.cfg["zoom"])
        if z > 1.001:
            qp.setPen(QColor(150, 190, 150))
            qp.drawText(QRect(0, 0, self.width() - SIDE - 4, BAR_H),
                        Qt.AlignVCenter | Qt.AlignRight, f"{z:.1f}x")

        if not self.alive():
            qp.setPen(QColor(120, 60, 60))
            qp.drawText(self.picture_rect(), Qt.AlignCenter, "waiting for client")

        g = self.grip_rect()
        qp.setPen(QColor(110, 120, 140))
        for i in (3, 6, 9):
            qp.drawLine(g.right() - i, g.bottom() - 2, g.right() - 2, g.bottom() - i)

    # -- input ------------------------------------------------------------

    def mousePressEvent(self, ev):
        pos = ev.position().toPoint()
        btn = ev.button()

        if btn == Qt.RightButton:
            if self.picture_rect().contains(pos):
                self._pan_from = ev.globalPosition().toPoint()
                self._pan_moved = False
            else:
                self.show_menu(ev.globalPosition().toPoint())
            return

        if btn == Qt.MiddleButton:
            self.reset_lens()
            return

        if btn != Qt.LeftButton:
            return

        if self.grip_rect().contains(pos):
            self._resizing = True
            self._resize_origin = (ev.globalPosition().toPoint(), self.width())
        elif pos.y() < BAR_H:
            self._drag_off = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif self.picture_rect().contains(pos) and self.alive():
            focus_window(self.src_hwnd)

    def mouseMoveEvent(self, ev):
        gp = ev.globalPosition().toPoint()

        if self._pan_from is not None:
            d = gp - self._pan_from
            if not self._pan_moved and (abs(d.x()) + abs(d.y())) < DRAG_SLOP:
                return
            self._pan_moved = True
            self._pan_from = gp
            if float(self.cfg["zoom"]) > 1.001:
                self.pan(d.x(), d.y())
                self.setCursor(Qt.ClosedHandCursor)
            return

        if self._resizing:
            start, w0 = self._resize_origin
            self.set_width(w0 + (gp.x() - start.x()))
            return

        if self._drag_off is not None:
            self.move(gp - self._drag_off)
            return

        pos = ev.position().toPoint()
        if self.grip_rect().contains(pos):
            self.setCursor(Qt.SizeFDiagCursor)
        elif pos.y() < BAR_H:
            self.setCursor(Qt.SizeAllCursor)
        elif self.picture_rect().contains(pos) and self.alive():
            self.setCursor(Qt.OpenHandCursor if float(self.cfg["zoom"]) > 1.001
                           else Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.RightButton and self._pan_from is not None:
            moved = self._pan_moved
            self._pan_from = None
            self._pan_moved = False
            self.unsetCursor()
            if moved:
                self.save()
            else:
                self.show_menu(ev.globalPosition().toPoint())
            return

        if self._resizing or self._drag_off is not None:
            self._resizing = False
            self._drag_off = None
            self.save()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.picture_rect().contains(ev.position().toPoint()):
            self.reset_lens()

    def wheelEvent(self, ev):
        notches = ev.angleDelta().y() / 120.0
        if not notches:
            return
        if ev.modifiers() & Qt.ControlModifier:
            self.set_width(self.width() + int(notches) * 40)
            self.save()
        elif self.picture_rect().contains(ev.position().toPoint()):
            self.zoom_at(notches, ev.position().toPoint())
            self.save()

    def set_width(self, w):
        w = int(clamp(w, MIN_W, self.max_width()))
        self.resize(w, self._height_for(w))

    def resizeEvent(self, _):
        self.push()

    def moveEvent(self, _):
        self.push()

    # -- menu -------------------------------------------------------------

    def show_menu(self, global_pos):
        m = QMenu(self)

        a = QAction("Reset lens (full frame)", m)
        a.triggered.connect(self.reset_lens)
        m.addAction(a)

        m.addSeparator()
        a = QAction("Hide tile while its client is focused", m, checkable=True)
        a.setChecked(bool(CONFIG.get("auto_hide", True)))
        a.triggered.connect(lambda checked: set_auto_hide(checked))
        m.addAction(a)

        m.addSeparator()
        for z in (1.5, 2.0, 3.0, 4.0, 6.0):
            a = QAction(f"Zoom {z:g}x", m, checkable=True)
            a.setChecked(abs(float(self.cfg["zoom"]) - z) < 0.05)
            a.triggered.connect(lambda _c, zz=z: self.set_zoom(zz))
            m.addAction(a)

        m.addSeparator()
        for pct in (40, 60, 80, 100):
            val = int(255 * pct / 100)
            a = QAction(f"Opacity {pct}%", m, checkable=True)
            a.setChecked(abs(self.cfg.get("opacity", 255) - val) < 4)
            a.triggered.connect(lambda _c, v=val: self.set_opacity(v))
            m.addAction(a)

        m.addSeparator()
        for w in (320, 480, 640, 800, 1000):
            a = QAction(f"Width {w}px", m)
            a.triggered.connect(lambda _c, ww=w: (self.set_width(ww), self.save()))
            m.addAction(a)

        m.addSeparator()
        about = QAction(f"{APP_NAME} {APP_VERSION}  by {APP_AUTHOR}", m)
        about.setEnabled(False)
        m.addAction(about)
        q = QAction("Quit SWG-O", m)
        q.triggered.connect(QApplication.quit)
        m.addAction(q)
        m.exec(global_pos)

    def set_opacity(self, val):
        self.cfg["opacity"] = val
        self.push()
        self.save()

    def save(self):
        self.cfg.update({"x": self.x(), "y": self.y(), "w": self.width()})
        save_config()


# --------------------------------------------------------------------------
# manager
# --------------------------------------------------------------------------

CONFIG = {"tiles": [{}, {}], "auto_hide": True}
TILES = []          # populated in main(), used by the menu toggle


def load_config():
    global CONFIG
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data.get("tiles"), list) and data["tiles"]:
            CONFIG = data
    except (OSError, ValueError):
        pass
    while len(CONFIG["tiles"]) < 2:
        CONFIG["tiles"].append({})
    CONFIG.setdefault("auto_hide", True)
    # Written out so a user on a different client build can change it by hand.
    CONFIG.setdefault("client_class", DEFAULT_CLIENT_CLASS)
    save_config()


def set_auto_hide(enabled):
    """Global toggle. Applies to both tiles from either tile's menu."""
    CONFIG["auto_hide"] = bool(enabled)
    save_config()
    fg = user32.GetForegroundWindow()
    for t in TILES:
        t.apply_visibility(fg)


def save_config():
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(CONFIG, fh, indent=2)
    except OSError:
        pass


def main():
    load_config()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_AUTHOR)
    icon_path = _asset("swgo.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    # Tiles hide themselves, so never tie process lifetime to window visibility.
    app.setQuitOnLastWindowClosed(False)

    tiles = [Tile(i, CONFIG["tiles"][i]) for i in range(2)]
    TILES.extend(tiles)
    for t in tiles:
        t.show()

    def rescan():
        clients = find_clients()
        for i, t in enumerate(tiles):
            want = clients[i][0] if i < len(clients) else None
            if want != t.src_hwnd:
                if want:
                    t.attach(want)
                    started = clients[i][2]
                    if not t.cfg.get("label"):
                        stamp = started.strftime("%H:%M") if started else "?"
                        t.cfg["label"] = f"Client {i + 1}  (pid {clients[i][1]}, {stamp})"
                else:
                    t.detach()
                t.update()
            elif want and not t.thumb:
                t.attach(want)

    def focus_watch():
        fg = user32.GetForegroundWindow()
        for t in tiles:
            t.apply_visibility(fg)

    # Ctrl+C from a console lands inside whichever timer callback is running
    # and prints a traceback. Turn it into a clean quit instead.
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    rescan()
    focus_watch()

    rescan_timer = QTimer()
    rescan_timer.timeout.connect(rescan)
    rescan_timer.start(RESCAN_MS)

    focus_timer = QTimer()
    focus_timer.timeout.connect(focus_watch)
    focus_timer.start(FOCUS_POLL_MS)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
