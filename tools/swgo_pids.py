#!/usr/bin/env python3
"""
swg_pids.py - enumerate visible top-level windows and their owning processes.

Windows only. Standard library only, no pip installs.

Usage:
    python swg_pids.py                  # likely game windows (size-filtered)
    python swg_pids.py --all            # every visible top-level window
    python swg_pids.py --match swg      # substring filter on exe / title / class
    python swg_pids.py --watch 2        # re-poll every 2 seconds, Ctrl-C to stop
    python swg_pids.py --json           # machine-readable dump
    python swg_pids.py --all --json > windows.json

Run this with both clients logged in and sitting at the character screen or
in-world. If the clients run elevated and this script does not, exe path and
start time come back as "?" for those rows; the PID is still correct. Rerun
from an admin prompt to fill those in.

Rows are sorted by process start time, so the first-launched client is first.
"""

import argparse
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from datetime import datetime

if sys.platform != "win32":
    sys.exit("This script only runs on Windows.")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

GW_OWNER = 4
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DWMWA_CLOAKED = 14

# Substrings that flag a row as a probable game client or launcher. Purely
# cosmetic: it drives the CANDIDATE column, never what gets enumerated.
HINTS = ("swg", "galaxies", "restoration", "launcher", "star wars")


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.GetProcessTimes.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME),
]
kernel32.GetProcessTimes.restype = wintypes.BOOL

dwmapi.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
]
dwmapi.DwmGetWindowAttribute.restype = ctypes.HRESULT


def window_text(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def is_cloaked(hwnd):
    """UWP and some shell windows report visible but are composited away."""
    val = wintypes.DWORD()
    hr = dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val)
    )
    return hr == 0 and val.value != 0


def filetime_to_dt(ft):
    ticks = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    if ticks == 0:
        return None
    # 100ns ticks since 1601-01-01 -> unix epoch
    return datetime.fromtimestamp((ticks - 116444736000000000) / 10_000_000)


def process_details(pid):
    """Returns (exe_path, start_datetime). Either may be None without rights."""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None, None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        exe = None
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            exe = buf.value

        created = FILETIME()
        exited = FILETIME()
        kern = FILETIME()
        usr = FILETIME()
        start = None
        if kernel32.GetProcessTimes(
            h,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kern),
            ctypes.byref(usr),
        ):
            start = filetime_to_dt(created)
        return exe, start
    finally:
        kernel32.CloseHandle(h)


def enumerate_windows(include_all=False, min_side=200):
    rows = []

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True  # tooltip, dialog, or other owned window
        if is_cloaked(hwnd):
            return True

        wr = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(wr))
        w, h = wr.right - wr.left, wr.bottom - wr.top

        cr = RECT()
        user32.GetClientRect(hwnd, ctypes.byref(cr))

        minimized = bool(user32.IsIconic(hwnd))
        if not include_all and not minimized and (w < min_side or h < min_side):
            return True

        pid = wintypes.DWORD()
        tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe, start = process_details(pid.value)
        base = os.path.basename(exe) if exe else "?"

        haystack = " ".join(
            x.lower() for x in (base, window_text(hwnd), class_name(hwnd), exe or "")
        )
        rows.append(
            {
                "hwnd": hwnd,
                "pid": pid.value,
                "tid": tid,
                "exe_name": base,
                "exe_path": exe or "?",
                "title": window_text(hwnd),
                "class": class_name(hwnd),
                "x": wr.left,
                "y": wr.top,
                "w": w,
                "h": h,
                "client_w": cr.right - cr.left,
                "client_h": cr.bottom - cr.top,
                "minimized": minimized,
                "started": start.isoformat(timespec="seconds") if start else "?",
                "_start_sort": start.timestamp() if start else float("inf"),
                "candidate": any(k in haystack for k in HINTS),
            }
        )
        return True

    if not user32.EnumWindows(EnumWindowsProc(callback), 0):
        err = ctypes.get_last_error()
        if err:
            raise ctypes.WinError(err)

    rows.sort(key=lambda r: (r["_start_sort"], r["pid"]))
    return rows


def print_table(rows):
    if not rows:
        print("No matching windows. Try --all, or check that both clients are up.")
        return

    hdr = ("PID", "HWND", "EXE", "CLASS", "GEOMETRY", "STATE", "STARTED", "TITLE")
    table = []
    for r in rows:
        geom = f'{r["w"]}x{r["h"]}+{r["x"]}+{r["y"]}'
        if r["minimized"]:
            state = "min"
        elif r["client_w"] == r["w"] and r["client_h"] == r["h"]:
            state = "borderless"
        else:
            state = "windowed"
        started = r["started"][11:] if r["started"] != "?" else "?"
        mark = "*" if r["candidate"] else " "
        table.append(
            (
                str(r["pid"]),
                hex(r["hwnd"]),
                r["exe_name"],
                r["class"],
                geom,
                state,
                started,
                (mark + " " + r["title"]).rstrip(),
            )
        )

    widths = [max(len(hdr[i]), max(len(row[i]) for row in table)) for i in range(len(hdr))]
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*hdr))
    print("  ".join("-" * w for w in widths))
    for row in table:
        print(fmt.format(*row))

    groups = {}
    for r in rows:
        groups.setdefault(r["exe_name"], []).append(r["pid"])
    print()
    for exe, pids in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(pids) > 1:
            print(f"{exe}: {len(pids)} windows, pids {', '.join(map(str, pids))}")
    print("\n* = matched a game-related keyword. Verify by hand, do not trust it.")
    if any(r["exe_path"] == "?" for r in rows):
        print("Some rows show '?' for exe. Rerun from an elevated prompt.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="include small and utility windows")
    ap.add_argument("--match", metavar="STR", help="substring filter on exe, title, or class")
    ap.add_argument("--watch", type=float, metavar="SEC", help="re-poll every SEC seconds")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument("--min-side", type=int, default=200, help="minimum window edge in px (default 200)")
    args = ap.parse_args()

    def collect():
        rows = enumerate_windows(include_all=args.all, min_side=args.min_side)
        if args.match:
            m = args.match.lower()
            rows = [
                r
                for r in rows
                if m in r["exe_name"].lower()
                or m in r["title"].lower()
                or m in r["class"].lower()
                or m in r["exe_path"].lower()
            ]
        for r in rows:
            r.pop("_start_sort", None)
        return rows

    if args.watch:
        try:
            while True:
                rows = collect()
                if args.json:
                    print(json.dumps(rows, indent=2))
                else:
                    os.system("cls")
                    print(datetime.now().strftime("%H:%M:%S"), "\n")
                    print_table(rows)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            pass
        return

    rows = collect()
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print_table(rows)


if __name__ == "__main__":
    main()
