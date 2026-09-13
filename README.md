<div align="center">

<img src="docs/swgo_256.png" width="128" alt="SWG-O">

# SWG-O

**Live preview tiles for Star Wars Galaxies clients.**

Watch for a tell on your other character while you're in a browser, a
spreadsheet, or your other client. Click a tile to jump straight to it.

[Download](../../releases/latest) · [Build from source](#building-from-source) · [Report a problem](../../issues)

</div>

---

## What it does

Small always-on-top windows, one per running client, each showing that client
live. Scroll to zoom into the chat box, click to switch characters, and a tile
hides itself while you're already in that client.

The tiles are real live views, not screenshots. They use `DwmRegisterThumbnail`,
the same Windows compositor feature that draws taskbar hover previews, so the
GPU is mirroring a surface it already has. No capture loop, no frame copying,
no measurable framerate cost.

SWG-O reads nothing from the game. No memory access, no packet inspection, no
input injection, no files touched. It asks Windows to draw a second copy of a
window you already have open.

## Install

Grab the installer from [Releases](../../releases/latest) and run it.

Windows will show **"Windows protected your PC"** because the installer isn't
signed by a recognised publisher. Click **More info**, then **Run anyway**. If
you'd rather not, [build it yourself](#building-from-source); it's one command.

Installs per-user under `%LOCALAPPDATA%\Programs\SWG-O`. No admin rights, no
UAC prompt.

## Requirements

Windows 10 or 11.

**Clients must run borderless windowed.** Exclusive fullscreen bypasses the
Windows compositor, and the tile renders black.

**Never minimize a client.** Windows stops updating a minimized window and the
tile freezes on the last frame. Move it off-screen or behind something instead.

## Controls

Over the picture:

| Input | Action |
|---|---|
| Wheel | Zoom the lens, 1x to 8x, anchored to the cursor |
| Ctrl + wheel | Resize the tile |
| Right-drag | Pan the lens |
| Right-click | Menu |
| Left-click | Bring that client to the foreground |
| Middle-click / double-click | Reset to full frame |

On the frame:

| Input | Action |
|---|---|
| Drag the title strip | Move the tile |
| Drag the bottom-right corner | Resize the tile |

Zoom is anchored to the pointer, so putting the cursor on your chat box and
scrolling takes you straight there without needing to pan.

## Settings

`%APPDATA%\SWG-O\swgo.json`, written automatically. Tile positions, sizes,
zoom, lens position and opacity all persist. Zoom and lens are stored as
fractions of the client window, so they survive a resolution change.

### If the tiles say "waiting for client"

Your client build uses a different window class. Find yours:

```
py tools\swgo_pids.py
```

Run it with a client open, find your client in the list, and copy the value
from the `CLASS` column. Then edit `swgo.json`:

```json
"client_class": "whatever CLASS printed"
```

Restart SWG-O. The helper needs Python; if you don't have it, open an issue
with your client build and someone can read the value off theirs.

`swgo_pids.py` is also useful on its own. It prints every visible window with
its PID, window class, geometry and whether it's borderless, which is how you
confirm your clients are in the right display mode.

## Building from source

```
git clone https://github.com/YOURNAME/SWG-O.git
cd SWG-O
py -m pip install PySide6
py swgo.py
```

That's the whole dev loop. `swgo.py` runs directly.

To produce the distributable:

```
build.bat            release build
build.bat debug      console attached, so startup errors are visible
```

Output lands in `dist\SWG-O\`. Then compile `installer.iss` with
[Inno Setup 6](https://jrsoftware.org/isdl.php) for the setup exe.

To regenerate the icon (needs `pillow`):

```
py tools\make_icon.py
```

### Notes for anyone hacking on it

Most of `swgo.py` is `ctypes` against `user32` and `dwmapi`; only the widget
layer needs Qt. Three things are easy to get wrong:

- `rcDestination` is in the destination window's **client** coordinates, not
  screen coordinates, and in **physical** pixels while Qt hands you logical
  ones. Multiply by `devicePixelRatioF()` or the picture mis-sizes on any
  display above 100% scaling.
- DWM composites the thumbnail **over** the destination window's own painting,
  so all chrome has to live in the margins around the picture.
- Don't `pip uninstall PySide6-Addons` to save space. It shares MSVC runtime
  DLLs with PySide6-Essentials and removing it breaks QtCore. Install
  `PySide6-Essentials` alone instead if you want a smaller footprint.

## Credit

The idea is EVE-O Preview's, which has done this for EVE Online for years.
SWG-O is an independent implementation for Star Wars Galaxies, not a fork or a
port.

## License

MIT. See [LICENSE](LICENSE).

Star Wars Galaxies is a trademark of Lucasfilm Ltd. This project is an
unofficial fan tool with no affiliation to Lucasfilm, Sony Online
Entertainment, Daybreak, or any server operator.
