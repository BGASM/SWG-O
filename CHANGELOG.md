# Changelog

## 1.0.0

First release.

- Live DWM thumbnail tiles, one per running client
- Cursor-anchored wheel zoom, 1x to 8x, with right-drag panning
- Left-click a tile to bring that client to the foreground
- Auto-hide: a tile hides itself while its own client is focused
- Per-tile opacity, size and position, persisted to `%APPDATA%\SWG-O\swgo.json`
- Clients identified by window class, ordered by launch time, with the class
  overridable in the config for other client builds
- Tiles clamp themselves back on-screen when a saved layout does not fit the
  current monitor arrangement
- `tools/swgo_pids.py` for finding your client's window class and confirming
  it is running borderless
