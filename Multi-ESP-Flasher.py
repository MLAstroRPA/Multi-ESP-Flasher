#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-ESP-Flasher
=================
Công cụ CLI flash LIÊN TỤC (multi-flash) cho nhiều thiết bị ESP32 / ESP8266.

Tính năng:
    - BƯỚC 1: chọn LOẠI ESP (ESP32 / ESP32-S3 / ESP32-C3 / ESP8266).
              Ghi nhớ lựa chọn vào .db.txt (cạnh exe) và tự nạp lại khi mở.
    - BƯỚC 2: quét các THƯ MỤC CON cùng cấp với file exe để liệt kê sản phẩm phần cứng.
    - BƯỚC 3: sau khi chọn sản phẩm, chọn LẦN LƯỢT các file bin của loại ESP
              đã chọn (ESP32: bootloader, partitions, firmware, spiffs;
              ESP8266: firmware, spiffs) + mục cuối cho combine.bin (merged).
              Ghi nhớ lựa chọn cho từng sản phẩm bằng file .db.txt (cạnh exe),
              tự nạp lại khi mở; nếu thư mục sản phẩm không còn thì cập nhật
              lại db.
    - BƯỚC 4: chọn AUTO / CONFIRM MULTI FLASH
    - BƯỚC 5: quét & chọn cổng COM
    - BƯỚC 6: vòng lặp flash
    - BƯỚC 7: báo cáo số lượng board đã nạp
"""

import os
import re
import sys
import json
import time
import ctypes
import subprocess

APP_VERSION = "1.1.0"
APP_NAME = "Multi-ESP-Flasher"
DB_FILE = "Multi-ESP-Flasher.db.txt"
# Khoá "đặc biệt" trong db.txt dùng để ghi nhớ lựa chọn loại ESP (không phải sản phẩm).
CHIP_DB_KEY = "__chip__"

IS_WINDOWS = os.name == "nt"

# ---------------------------------------------------------------------------
# Cấu hình theo từng LOẠI ESP (BƯỚC 1)
#   label         : tên hiển thị trong menu
#   chip          : giá trị truyền cho esptool (--chip)
#   baud          : tốc độ nạp
#   kinds         : các slot file rời (thứ tự hiển thị ở bước chọn file)
#   addr          : offset ghi cho từng slot file rời
#   erase_ota     : vùng OTA boot data cần xoá trước khi flash (None = không xoá)
#   combined_addr : offset cho file gộp (merged)
# ---------------------------------------------------------------------------
CHIP_PROFILES = {
    "esp32": {
        "key":    "esp32",
        "label":  "ESP32     | bootloader 0x1000 · app 0x10000 · spiffs 0x290000",
        "chip":   "esp32",
        "baud":   "921600",
        "kinds":  ("bootloader", "partitions", "firmware", "spiffs"),
        "addr":   {"bootloader": "0x1000", "partitions": "0x8000",
                   "firmware": "0x10000", "spiffs": "0x290000"},
        "erase_ota": ("0xE000", "0x2000"),
        "combined_addr": "0x0",
    },
    "esp32s3": {
        "key":    "esp32s3",
        "label":  "ESP32-S3  | bootloader 0x0 · app 0x10000 · spiffs 0x290000",
        "chip":   "esp32s3",
        "baud":   "921600",
        "kinds":  ("bootloader", "partitions", "firmware", "spiffs"),
        "addr":   {"bootloader": "0x0", "partitions": "0x8000",
                   "firmware": "0x10000", "spiffs": "0x290000"},
        "erase_ota": ("0xE000", "0x2000"),
        "combined_addr": "0x0",
    },
    "esp32c3": {
        "key":    "esp32c3",
        "label":  "ESP32-C3  | bootloader 0x0 · app 0x10000 · spiffs 0x290000",
        "chip":   "esp32c3",
        "baud":   "921600",
        "kinds":  ("bootloader", "partitions", "firmware", "spiffs"),
        "addr":   {"bootloader": "0x0", "partitions": "0x8000",
                   "firmware": "0x10000", "spiffs": "0x290000"},
        "erase_ota": ("0xE000", "0x2000"),
        "combined_addr": "0x0",
    },
    "esp8266": {
        "key":    "esp8266",
        "label":  "ESP8266   | firmware 0x0 · spiffs 0x100000 (không có vùng OTA)",
        "chip":   "esp8266",
        "baud":   "460800",
        "kinds":  ("firmware", "spiffs"),
        "addr":   {"firmware": "0x0", "spiffs": "0x100000"},
        "erase_ota": None,
        "combined_addr": "0x0",
    },
}
CHIP_ORDER = ("esp32", "esp32s3", "esp32c3", "esp8266")
DEFAULT_CHIP = "esp32"

# Lưu lỗi flash/esptool cuối cùng để hiển thị lại ở BƯỚC 7 (vì BƯỚC 7 xóa màn hình).
LAST_ERROR = ""

if IS_WINDOWS:
    import msvcrt
else:
    msvcrt = None


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------
def enable_ansi():
    if not IS_WINDOWS:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def set_utf8_codepage():
    if IS_WINDOWS:
        try:
            os.system("chcp 65001 >nul")
        except Exception:
            pass


def configure_console():
    """Tắt QuickEdit Mode để bấm chuột không làm đóng băng console."""
    if not IS_WINDOWS:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            new_mode = (mode.value | 0x0080) & ~0x0040
            kernel32.SetConsoleMode(handle, new_mode)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Font console (Windows) - phóng to chữ gấp đôi cho dòng tổng kết
# ---------------------------------------------------------------------------
class _COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _CONSOLE_FONT_INFOEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("nFont", ctypes.c_ulong),
        ("dwFontSize", _COORD),
        ("FontFamily", ctypes.c_uint),
        ("FontWeight", ctypes.c_uint),
        ("FaceName", ctypes.c_wchar * 32),
    ]


def _temporarily_double_font():
    if not IS_WINDOWS:
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        font = _CONSOLE_FONT_INFOEX()
        font.cbSize = ctypes.sizeof(_CONSOLE_FONT_INFOEX)
        if not kernel32.GetCurrentConsoleFontEx(handle, False, ctypes.byref(font)):
            return None
        old = (font.dwFontSize.X, font.dwFontSize.Y)
        font.dwFontSize.X = max(1, old[0] * 2)
        font.dwFontSize.Y = max(1, old[1] * 2)
        kernel32.SetCurrentConsoleFontEx(handle, False, ctypes.byref(font))
        return (kernel32, handle, font, old)
    except Exception:
        return None


def _restore_console_font(ctx):
    if not ctx:
        return
    try:
        kernel32, handle, font, old = ctx
        font.dwFontSize.X = old[0]
        font.dwFontSize.Y = old[1]
        kernel32.SetCurrentConsoleFontEx(handle, False, ctypes.byref(font))
    except Exception:
        pass


def _c(text, code):
    if os.getenv("NO_COLOR"):
        return text
    return f"{code}{text}\033[0m"


def red(t):    return _c(t, "\033[91m")
def green(t):  return _c(t, "\033[92m")
def yellow(t): return _c(t, "\033[93m")
def cyan(t):   return _c(t, "\033[96m")
def bold(t):   return _c(t, "\033[1m")


def info(msg): print(cyan("[*] ") + msg)
def ok(msg):   print(green("[OK] ") + msg)
def warn(msg): print(yellow("[!] ") + msg)
def err(msg):  print(red("[ERR] ") + msg)


def banner():
    print("=" * 62)
    print("          M U L T I - E S P - F L A S H E R   v" + APP_VERSION)
    print("      Quét sản phẩm & flash liên tục nhiều thiết bị ESP32 / ESP8266")
    print("   ESP32: bootloader | partitions | firmware | spiffs (+ combined)")
    print("   ESP8266: firmware | spiffs (+ combined)")
    print("=" * 62)
    print("   Author: Nguyễn Công Đức    |    congduc1352@gmail.com")


def _close_splash():
    try:
        import pyi_splash
        time.sleep(3.0)   # tăng thời gian hiển thị splash (hình giới thiệu) lên 3 giây
        pyi_splash.close()
    except Exception:
        pass


def ask_yn(msg):
    while True:
        try:
            ans = input(bold(msg) + " [y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def pause_end():
    try:
        input("\nNhấn Enter để đóng cửa sổ...")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Key reading (Windows)
# ---------------------------------------------------------------------------
def _getch_timeout(timeout):
    if msvcrt is None:
        return None
    t0 = time.time()
    while not msvcrt.kbhit() and time.time() - t0 < timeout:
        time.sleep(0.005)
    if not msvcrt.kbhit():
        return None
    return msvcrt.getch()


def read_key(blocking=True):
    """Đọc phím. Trả về: up/down/left/right/esc/enter/refresh/f5/del/key/None."""
    if msvcrt is None:
        return None
    if not blocking and not msvcrt.kbhit():
        return None
    ch = msvcrt.getch()
    if ch in (b"\x00", b"\xe0"):
        ch2 = _getch_timeout(0.1)
        if ch2 is None:
            return "ext"
        return {b"H": "up", b"P": "down", b"K": "left", b"M": "right",
                b"S": "del"}.get(ch2, "ext")
    if ch == b"\x1b":
        if blocking:
            time.sleep(0.03)
        ch2 = _getch_timeout(0.05)
        if ch2 is None:
            return "esc"
        if ch2 in (b"[", b"O"):
            ch3 = _getch_timeout(0.05)
            if ch3 is None:
                return "ext"
            return {b"A": "up", b"B": "down", b"C": "right", b"D": "left"}.get(ch3, "ext")
        return "ext"
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch in (b"R", b"r"):
        return "refresh"
    if ch in (b"F", b"f"):
        return "f5"
    return "key"


def flush_keys():
    if msvcrt is None:
        return
    try:
        while msvcrt.kbhit():
            msvcrt.getch()
    except Exception:
        pass


def arrow_menu(title, items, allow_refresh=False, refresh_fn=None, start_idx=0):
    """Menu ↑/↓, Enter xác nhận, ESC hủy. Trả về value hoặc None."""
    idx = start_idx
    while True:
        if items:
            idx = max(0, min(idx, len(items) - 1))
        header = [
            "=" * 62,
            "  " + title,
            "  Dùng ↑/↓ để chọn, Enter xác nhận, ESC hủy."
            + ("  R/F5 để quét lại." if allow_refresh else ""),
            "=" * 62,
            "",
        ]
        lines = []
        if not items:
            lines.append(red("  (Không có lựa chọn nào)"
                             + ("  — bấm R để quét lại" if allow_refresh else "")))
        else:
            for i, (label, _v) in enumerate(items):
                marker = "\033[7m> " if i == idx else "  "
                end = "\033[0m" if i == idx else ""
                lines.append(marker + label + end)
        lines.append("")
        lines.append("  Nhấn ESC để hủy.")

        if IS_WINDOWS:
            os.system("cls")
        else:
            os.system("clear")
        print("\n".join(header + lines))

        key = read_key(True)
        if not items:
            if key == "esc":
                return None
            if key in ("refresh", "f5") and allow_refresh:
                items = refresh_fn() if refresh_fn else []
                idx = 0
            continue
        if key == "up":
            idx = (idx - 1) % len(items)
        elif key == "down":
            idx = (idx + 1) % len(items)
        elif key in ("refresh", "f5") and allow_refresh:
            items = refresh_fn() if refresh_fn else []
            idx = 0
        elif key == "enter":
            return items[idx][1]
        elif key == "esc":
            return None


def _visible_len(s):
    return len(re.sub(r"\x1b\[[0-9;]*m", "", s))


def console_width():
    """Chiều rộng console (số cột)."""
    try:
        import shutil
        w = shutil.get_terminal_size().columns
        return w if w and w > 10 else 80
    except Exception:
        return 80


def truncate_line(s, width):
    """Cắt dòng cho vừa bề rộng console (giữ nguyên mã màu ANSI) để tránh wrap text
    khi đường dẫn file quá dài."""
    if width <= 0 or _visible_len(s) <= width:
        return s
    out = []
    vis = 0
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\x1b":
            j = s.find("m", i)
            if j == -1:
                break
            out.append(s[i:j + 1])
            i = j + 1
            continue
        if vis >= width:
            break
        out.append(ch)
        vis += 1
        i += 1
    result = "".join(out)
    if "\x1b" in result and not result.endswith("\033[0m"):
        result += "\033[0m"
    return result


def _focus_console():
    """Trả focus về cửa sổ console sau khi đóng hộp thoại chọn file."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GetConsoleWindow.restype = ctypes.wintypes.HWND
        user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
        user32.BringWindowToTop.argtypes = [ctypes.wintypes.HWND]
        user32.GetWindowThreadProcessId.argtypes = \
            [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.c_ulong)]
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        user32.AttachThreadInput.argtypes = \
            [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]

        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        user32.ShowWindow(hwnd, 9)
        fg = user32.GetForegroundWindow()
        current_tid = kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg, None)
        attached = False
        if fg_tid and fg_tid != current_tid:
            attached = bool(user32.AttachThreadInput(current_tid, fg_tid, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(current_tid, fg_tid, False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Chọn file (hộp thoại tkinter + fallback nhập thủ công)
# ---------------------------------------------------------------------------
def _tk_pick(title, multi, initialdir=None):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        try:
            kwargs = {"title": title,
                      "filetypes": [("Bin files", "*.bin"), ("All files", "*.*")],
                      "initialdir": initialdir}
            if multi:
                files = filedialog.askopenfilenames(**kwargs)
                result = list(files)
            else:
                file = filedialog.askopenfilename(**kwargs)
                result = [file] if file else []
        finally:
            root.destroy()
        time.sleep(0.05)
        _focus_console()
        return result
    except Exception:
        return None


def pick_single(kind, initialdir=None):
    files = _tk_pick(f"Chọn {kind}.bin", multi=False, initialdir=initialdir)
    if files is None:
        print("  (Hộp thoại không khả dụng — vui lòng nhập đường dẫn thủ công)")
        path = input(f"  Đường dẫn {kind}.bin (Enter để bỏ qua): ").strip().strip('"')
        return path if path else None
    if not files:
        return None
    return files[0]


def valid_slot_path(p):
    """File db hợp lệ cho slot: chỉ cần file tồn tại thật trên đĩa.
    Không xét tên chuẩn {kind}.bin — sai tên / không tìm thấy -> coi là chưa chọn."""
    if not p:
        return False
    return os.path.isfile(p)


# ---------------------------------------------------------------------------
# ĐANG KIỂM TRA ESP-TOOL-CLI
# ---------------------------------------------------------------------------
def esptool_installed():
    try:
        import importlib
        importlib.import_module("esptool")
        return True
    except Exception:
        return False


def install_esptool():
    print()
    info("Đang cài đặt esptool + pyserial (các chương trình phụ thuộc)...")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "esptool", "pyserial"]
    print(cyan("$ ") + " ".join(cmd))
    try:
        proc = subprocess.run(cmd)
        return proc.returncode == 0
    except Exception as exc:
        err(f"Không thể chạy pip: {exc}")
        return False


def step1_check_esptool():
    print()
    print("ĐANG KIỂM TRA ESP-TOOL-CLI ...")
    if esptool_installed():
        ok("ESP-tool-cli (esptool) đã sẵn sàng.")
        return True

    print()
    warn("ESP-tool-cli (esptool) CHƯA được cài đặt.")
    if ask_yn("Bạn có muốn cài đặt esptool (bao gồm chương trình phụ thuộc) ngay bây giờ không?"):
        if not install_esptool():
            err("Cài đặt esptool thất bại.")
            print("  Hãy tự cài bằng lệnh:  python -m pip install esptool pyserial")
            pause_end()
            return False
        if not esptool_installed():
            err("esptool vẫn chưa sẵn sàng. Kiểm tra lại cài đặt Python/pip.")
            pause_end()
            return False
        ok("esptool đã được cài đặt thành công.")
        return True

    print()
    print(yellow("Bạn đã chọn KHÔNG cài đặt. Đóng cửa sổ."))
    pause_end()
    return False


# ---------------------------------------------------------------------------
# BƯỚC 1 - Chọn LOẠI ESP (ESP32 / ESP32-S3 / ESP32-C3 / ESP8266)
# ---------------------------------------------------------------------------
def select_chip_menu(default_key=DEFAULT_CHIP):
    """BƯỚC 1: chọn loại ESP. Trả về khoá profile (vd 'esp32') hoặc None nếu ESC."""
    idx = CHIP_ORDER.index(default_key) if default_key in CHIP_ORDER else 0
    items = []
    for key in CHIP_ORDER:
        prof = CHIP_PROFILES[key]
        mark = "  <- đã dùng lần trước" if key == default_key else ""
        items.append((f"{prof['label']}{mark}", key))
    return arrow_menu("BƯỚC 1: CHỌN LOẠI ESP", items, start_idx=idx)


def chip_label(chip_key):
    """Tên ngắn gọn của loại ESP (phần đầu của label)."""
    prof = CHIP_PROFILES.get(chip_key)
    if not prof:
        return str(chip_key)
    return prof["label"].split("|")[0].strip()


# ---------------------------------------------------------------------------
# BƯỚC 2 - Quét thư mục con cùng cấp với exe -> danh sách sản phẩm phần cứng
# ---------------------------------------------------------------------------
def exe_dir():
    return (os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))


def short_path(p):
    """Hiển thị link tắt dạng .\\tên_sản_phẩm\\xxx.bin (so với thư mục exe)."""
    try:
        rel = os.path.relpath(p, exe_dir())
        if not rel.startswith(".."):
            return ".\\" + rel
    except Exception:
        pass
    return os.path.basename(p)


def scan_products():
    """Quét các THƯ MỤC CON nằm CÙNG CẤP với file exe (trong thư mục chứa exe).

    Ví dụ: exe ở bin/Multi-ESP-Flasher.exe -> quét bin/TestFolder, ...
    """
    base = exe_dir()
    products = []
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name)
            if os.path.isdir(p) and not name.startswith("."):
                products.append((name, p))
    return products


def select_product(products):
    def _items():
        return [(name, name) for name, _ in scan_products()]
    items = [(name, name) for name, _ in products]
    if not items:
        warn("Không có thư mục sản phẩm nào (quét các thư mục con cùng cấp với exe).")
        return None
    return arrow_menu("BƯỚC 2: CHỌN SẢN PHẨM PHẦN CỨNG",
                      items, allow_refresh=True, refresh_fn=_items)


# ---------------------------------------------------------------------------
# Database (.db.txt) - ghi nhớ lựa chọn file cho từng sản phẩm
# ---------------------------------------------------------------------------
def db_path():
    return os.path.join(exe_dir(), DB_FILE)


def load_db():
    try:
        with open(db_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_db(db):
    try:
        with open(db_path(), "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        warn(f"Không lưu được db: {exc}")


def ensure_db():
    """Nạp db; nếu file db chưa tồn tại thì tạo ngay file db rỗng."""
    if not os.path.isfile(db_path()):
        save_db({})
    return load_db()


def sync_products_db(db, product_names):
    """Đồng bộ thư mục sản phẩm với db:
    - Có trong db nhưng thư mục không còn tồn tại -> xoá khỏi db.
    - Thư mục sản phẩm có thật nhưng chưa có trong db -> thêm vào db (mapping rỗng).
    """
    names = set(product_names)
    changed = False
    for key in list(db.keys()):
        if str(key).startswith("__"):
            continue    # khoá đặc biệt (vd __chip__) - không phải sản phẩm
        if key not in names:
            del db[key]
            changed = True
    for name in names:
        if name not in db:
            db[name] = {}
            changed = True
    if changed:
        save_db(db)


# ---------------------------------------------------------------------------
# BƯỚC 3 - Chọn lần lượt các file bin (+ combine.bin) cho sản phẩm
# ---------------------------------------------------------------------------
def configure_product_files(product_name, product_dir, db, profile, save_to_db=True):
    """BƯỚC 3: menu chọn LẦN LƯỢT các file bin cho sản phẩm; lưu vào db
    (save_to_db=False khi chọn file ngoài, không ghi nhớ db).
    Các slot hiển thị phụ thuộc LOẠI ESP đã chọn ở BƯỚC 1 (profile)."""
    slot_kinds = tuple(profile["kinds"]) + ("combined",)
    # Chỉ nạp lại các file db tồn tại thật trên đĩa;
    # không có db hoặc file không tìm thấy -> để "(chưa chọn)"
    mapping = {k: p for k, p in (db.get(product_name, {}) or {}).items()
               if valid_slot_path(p)}

    idx = 0
    entered = False

    def _persist():
        """Lưu ngay mapping hiện tại vào db (nếu có lưu)."""
        if save_to_db:
            db[product_name] = mapping
            save_db(db)

    while True:
        items = []
        for kind in slot_kinds:
            p = mapping.get(kind)
            name = f"{kind}.bin"
            if valid_slot_path(p):
                shown = short_path(p)
                label = f"{name:<14} -> {shown}"
            else:
                label = f"{name:<14} -> (chưa chọn)"
            items.append((label, kind))
        items.append(("Tiếp theo >>>", "__done__"))
        if not entered:
            # Chuyển từ BƯỚC 2 sang BƯỚC 3: đưa selector xuống mục cuối "Tiếp theo >>>"
            idx = len(items) - 1
            entered = True

        title = (f"  BƯỚC 3: CHỌN FILE CHO SẢN PHẨM \"{product_name}\" "
                 f"[{chip_label(profile['key'])}]"
                 if save_to_db else "  BƯỚC 3: CHỌN FILE BIN NGOÀI (KHÔNG LƯU)")
        note = ("  ENTER tại 'Tiếp theo >>>' để lưu & tiếp tục."
                if save_to_db else "  ENTER tại 'Tiếp theo >>>' để tiếp tục (không lưu).")
        header = [
            "=" * 62,
            title,
            "  ↑/↓ chọn · ENTER mở hộp chọn file · DEL xoá lựa chọn",
            note,
            "=" * 62,
            "",
        ]
        lines = []
        width = console_width()
        for i, (label, _v) in enumerate(items):
            if i == len(items) - 1:
                lines.append("")   # giãn cách 1 hàng trước "Tiếp theo >>>"
            marker = "\033[7m> " if i == idx else "  "
            end = "\033[0m" if i == idx else ""
            lines.append(truncate_line(marker + label + end, width))
        lines.append("")
        lines.append("  Nhấn ESC để quay lại chọn sản phẩm.")

        if IS_WINDOWS:
            os.system("cls")
        else:
            os.system("clear")
        print("\n".join(header + lines))

        key = read_key(True)
        if key == "up":
            idx = (idx - 1) % len(items)
        elif key == "down":
            idx = (idx + 1) % len(items)
        elif key == "del":
            value = items[idx][1]
            if value != "__done__" and value in mapping:
                del mapping[value]
                _persist()
                ok(f"Đã xoá lựa chọn {value}.bin.")
        elif key == "enter":
            value = items[idx][1]
            if value == "__done__":
                if save_to_db:
                    _persist()
                    ok("Đã lưu lựa chọn file vào db.")
                else:
                    ok("Không lưu lựa chọn (chế độ file ngoài).")
                return mapping
            default_dir = None
            cur = mapping.get(value)
            if cur and os.path.isfile(cur):
                default_dir = os.path.dirname(cur)
            if not default_dir and product_dir and os.path.isdir(product_dir):
                default_dir = product_dir
            path = pick_single(value, default_dir)
            if path:
                mapping[value] = path
                _persist()
                ok(f"Đã lưu lựa chọn {value}.bin.")
        elif key == "esc":
            # Lưu lần cuối trước khi quay lại/đóng ứng dụng
            _persist()
            return None
    return mapping


# ---------------------------------------------------------------------------
# BƯỚC 4 - Chọn chế độ flash
# ---------------------------------------------------------------------------
def select_mode_menu():
    items = [
        ("a) AUTO MULTI FLASH     - sau khi flash, tự phát hiện cổng COM online và flash tiếp", "auto"),
        ("b) CONFIRM MULTI FLASH  - sau khi flash, đợi nhấn Enter để flash tiếp / ESC thoát", "confirm"),
    ]
    return arrow_menu("BƯỚC 4: CHỌN CHẾ ĐỘ FLASH", items)


# ---------------------------------------------------------------------------
# BƯỚC 5 - Quét & chọn cổng COM
# ---------------------------------------------------------------------------
def list_ports():
    try:
        from serial.tools import list_ports
        items = []
        seen = set()
        for p in sorted(list_ports.comports(), key=lambda x: x.device):
            if p.device in seen:
                continue
            seen.add(p.device)
            items.append((p.device, p.description or ""))
        return items
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object"],
            capture_output=True, text=True, timeout=10).stdout
        return [(line.strip(), "") for line in out.splitlines()
                if line.strip().upper().startswith("COM")]
    except Exception:
        return []


def port_present(port):
    return any(dev.upper() == port.upper() for dev, _ in list_ports())


def select_com_port():
    def _items():
        return [(f"{dev}   {desc}".rstrip(), dev) for dev, desc in list_ports()]
    return arrow_menu("BƯỚC 5: QUÉT & CHỌN CỔNG COM",
                      _items(), allow_refresh=True, refresh_fn=_items)


# ---------------------------------------------------------------------------
# BƯỚC 6 - Vòng lặp flash
# ---------------------------------------------------------------------------
def run_esptool(args):
    global LAST_ERROR
    try:
        import esptool
    except Exception as exc:
        LAST_ERROR = f"Không thể nạp esptool: {exc}"
        err(LAST_ERROR)
        return 1
    print()
    print(cyan("$ esptool ") + " ".join(args))
    try:
        code = esptool.main(args)
        if code is None:
            return 0
        return int(code)
    except SystemExit as exc:
        if exc.code is None:
            return 0
        try:
            return int(exc.code)
        except Exception:
            return 1
    except KeyboardInterrupt:
        LAST_ERROR = "Flash bị hủy bởi Ctrl+C (không khuyến khích trong lúc flash)."
        err(LAST_ERROR)
        return -1
    except Exception as exc:
        LAST_ERROR = str(exc)
        err(f"esptool gặp lỗi: {exc}")
        return 1


def flash_once(port, mapping, profile):
    global LAST_ERROR
    chip = profile["chip"]
    baud = profile["baud"]
    addr = profile["addr"]
    kinds_order = profile["kinds"]
    combined_addr = profile["combined_addr"]
    erase_ota = profile["erase_ota"]

    def _erase_ota_region():
        if not erase_ota:
            return 0
        info(f"Đang xóa OTA boot data ({erase_ota[0]}, {erase_ota[1]}) ...")
        return run_esptool(["--chip", chip, "--port", port,
                            "erase-region", erase_ota[0], erase_ota[1]])

    # File combined/merged: 1 file ghi nguyên khối tại combined_addr
    if mapping.get("combined"):
        path = mapping["combined"]
        if not os.path.isfile(path):
            LAST_ERROR = f"File không tồn tại: {path}"
            err(LAST_ERROR)
            return 1
        if _erase_ota_region() != 0:
            LAST_ERROR = LAST_ERROR or "Xóa OTA boot data thất bại."
            err(LAST_ERROR)
            return 1
        info(f"Ghi flash combined (merged) @ {combined_addr} ...")
        return run_esptool(["--chip", chip, "--port", port, "--baud", baud,
                            "write-flash", "-z", combined_addr, path])

    kinds = [k for k in kinds_order if mapping.get(k)]
    for k in kinds:
        if not os.path.isfile(mapping[k]):
            LAST_ERROR = f"File không tồn tại: {mapping[k]}"
            err(LAST_ERROR)
            return 1

    # Xóa OTA boot data (chỉ với loại ESP có vùng OTA, ví dụ ESP32)
    if erase_ota and any(k in ("bootloader", "partitions", "firmware") for k in kinds):
        if _erase_ota_region() != 0:
            LAST_ERROR = LAST_ERROR or "Xóa OTA boot data thất bại."
            err(LAST_ERROR)
            return 1

    args = ["--chip", chip, "--port", port, "--baud", baud,
            "write-flash", "-z"]
    for k in kinds:
        args += [addr[k], mapping[k]]
    info("Ghi flash: " + ", ".join(f"{k} @ {addr[k]}" for k in kinds))
    return run_esptool(args)


def wait_port_state(port, want_present, label):
    print(f"  {label}  (ESC để thoát)")
    while port_present(port) != want_present:
        if read_key(False) == "esc":
            return False
        time.sleep(0.2)
    return True


def wait_online_countdown(port):
    print(f"  Cổng {port} đã online. Đợi 5 giây chống debounce trước khi flash tiếp...")
    flush_keys()
    for i in range(5, 0, -1):
        sys.stdout.write(f"\r    Flash tiếp trong {i:>2}s ... (ESC để thoát)   ")
        sys.stdout.flush()
        t0 = time.time()
        while time.time() - t0 < 1.0:
            if read_key(False) == "esc":
                sys.stdout.write("\r" + " " * 70 + "\r")
                sys.stdout.flush()
                print("  Đã thoát.")
                return False
            time.sleep(0.05)
    sys.stdout.write("\r" + " " * 70 + "\r")
    sys.stdout.flush()
    return True


def play_success_bell():
    """Phát tiếng chuông sắt "tinggg" ngay khi flash xong (Windows)."""
    if not IS_WINDOWS:
        return
    try:
        import wave
        import math
        import struct
        import random
        import tempfile
        import winsound
    except Exception:
        return
    try:
        SR = 44100
        F0 = 2500.0
        DUR = 1.6
        # (amp, ratio, decay) - partials phi điều hoà + tắt dần khác nhau => chuông sắt
        PARTS = [
            (0.85, 1.0,    1.0),   # fundamental - ngân dài nhất
            (0.85, 1.0025, 1.0),   # gần fundamental -> "beating" kim loại
            (0.50, 2.0,    1.6),   # octave
            (0.35, 2.76,   2.5),   # partial phi điều hoà ("clang")
            (0.15, 5.4,    4.3),   # partial cao - tắt rất nhanh
        ]
        random.seed(42)
        noise = [random.uniform(-1.0, 1.0) for _ in range(int(SR * 0.004))]
        frames = bytearray()
        for i in range(int(SR * DUR)):
            t = i / SR
            v = 0.0
            for amp, ratio, dec in PARTS:
                f = F0 * ratio
                v += amp * math.sin(2 * math.pi * f * t) * math.exp(-dec * t)
            if i < len(noise):
                v += noise[i] * 0.25 * math.exp(-60.0 * t)   # tiếng "tick" lúc gõ
            v = max(-1.0, min(1.0, v * 0.30))
            frames += struct.pack('<h', int(v * 32767))
        path = os.path.join(tempfile.gettempdir(), "mlastro_bell.wav")
        with wave.open(path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(bytes(frames))
        winsound.PlaySound(path, winsound.SND_FILENAME)
    except Exception:
        pass


def run_multi_flash(port, mapping, profile, mode):
    info(f"Bắt đầu flash lên {bold(port)} ...")
    print("  LƯU Ý: không cho phép thoát (ESC) trong lúc đang flash.")
    result = flash_once(port, mapping, profile)
    if result != 0:
        err("Flash THẤT BẠI. Kiểm tra cổng COM / kết nối rồi thử lại.")
        return "error"
    ok("Flash thành công!")
    play_success_bell()

    if mode == "confirm":
        print()
        print("  CONFIRM MODE: Flash xong.")
        print("  Nhấn Enter để flash tiếp, ESC để thoát.")
        while True:
            key = read_key(True)
            if key == "enter":
                return "again"
            if key == "esc":
                return "exit"
    else:
        print()
        print("  AUTO MODE: Rút USB thiết bị vừa flash, cắm thiết bị tiếp theo.")
        print("  Tool sẽ tự phát hiện cổng " + bold(port) + " online rồi flash tiếp.")
        print("  (ESC để thoát — ngoài lúc đang flash)")
        if port_present(port):
            if not wait_port_state(port, want_present=False,
                                   label=f"Đợi cổng {port} NGẮT kết nối (rút USB)..."):
                return "exit"
        if not wait_port_state(port, want_present=True,
                               label=f"Đợi cổng {port} KẾT NỐI lại (cắm thiết bị mới)..."):
            return "exit"
        if not wait_online_countdown(port):
            return "exit"
        return "again"


# ---------------------------------------------------------------------------
# BƯỚC 7 - Báo cáo số lượng
# ---------------------------------------------------------------------------
def step7_summary(flashed, error=""):
    if IS_WINDOWS:
        os.system("cls")
    else:
        os.system("clear")
    print("=" * 62)
    print("  BƯỚC 7: BÁO CÁO")
    print("=" * 62)
    print()
    ctx = _temporarily_double_font()
    try:
        print(bold(red(f"  Số board đã nạp: {flashed}")))
    finally:
        _restore_console_font(ctx)
    if error:
        print()
        print(yellow("  Lỗi: ") + str(error))
    print()
    print("  Nhấn Enter hoặc ESC để đóng cửa sổ.")
    flush_keys()
    while True:
        key = read_key(True)
        if key in ("enter", "esc"):
            return


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global LAST_ERROR
    enable_ansi()
    configure_console()
    set_utf8_codepage()
    banner()
    _close_splash()

    # ĐANG KIỂM TRA ESP-TOOL-CLI
    if not step1_check_esptool():
        return 1

    db = ensure_db()

    # BƯỚC 1: chọn LOẠI ESP (ghi nhớ lựa chọn vào db)
    saved_chip = db.get(CHIP_DB_KEY)
    if saved_chip not in CHIP_PROFILES:
        saved_chip = DEFAULT_CHIP
    chip_key = select_chip_menu(saved_chip)
    if chip_key is None:
        return 0        # ESC hủy -> đóng ứng dụng
    profile = CHIP_PROFILES[chip_key]
    if db.get(CHIP_DB_KEY) != chip_key:
        db[CHIP_DB_KEY] = chip_key
        save_db(db)

    while True:
        products = scan_products()
        sync_products_db(db, [n for n, _ in products])

        product = None
        product_dir = None
        save_to_db = True

        if not products:
            # Không có thư mục sản phẩm -> cho phép chọn file bin NGOÀI (không lưu db)
            print()
            print(red("  KHÔNG TÌM THẤY THƯ MỤC SẢN PHẨM!"))
            print(red("  Không có thư mục sản phẩm nào cùng cấp với file exe."))
            print()
            if not ask_yn(red("  Tiếp tục chọn file bin ngoài để flash?")):
                return 0    # từ chối -> đóng ứng dụng
            product = "(file ngoài)"
            save_to_db = False
        else:
            # BƯỚC 2: chọn sản phẩm phần cứng
            product = select_product(products)
            if product is None:
                return 0    # ESC hủy -> đóng ứng dụng
            product_dir = next((d for n, d in products if n == product), None)

        # BƯỚC 3: chọn lần lượt các file bin (+ combine) - ghi nhớ db
        mapping = configure_product_files(product, product_dir, db, profile,
                                          save_to_db=save_to_db)
        if mapping is None:
            continue    # ESC -> quay lại đầu (chọn sản phẩm / hỏi lại)
        if not mapping:
            warn("Không có file bin nào được chọn.")
            continue

        # BƯỚC 4: chọn chế độ
        mode = select_mode_menu()
        if mode is None:
            return 0    # ESC hủy -> đóng ứng dụng

        # BƯỚC 5: chọn cổng COM
        port = select_com_port()
        if port is None:
            return 0    # ESC hủy -> đóng ứng dụng

        # Tóm tắt + xác nhận
        print()
        print("=" * 62)
        print("  TÓM TẮT CẤU HÌNH")
        print("=" * 62)
        print(f"  Loại ESP : {chip_label(chip_key)}  (--chip {profile['chip']})")
        print(f"  Sản phẩm : {product}")
        print(f"  Cổng COM : {port}")
        print(f"  Chế độ   : {'AUTO MULTI FLASH' if mode == 'auto' else 'CONFIRM MULTI FLASH'}")
        print("  Files    :")
        if mapping.get("combined"):
            print(f"    {'combined':<12} -> {profile['combined_addr']} : {short_path(mapping['combined'])}")
        else:
            for k in profile["kinds"]:
                if mapping.get(k):
                    print(f"    {k:<12} -> {profile['addr'][k]} : {short_path(mapping[k])}")
        if not ask_yn("\nBắt đầu flash với cấu hình trên?"):
            continue

        # BƯỚC 6: vòng lặp flash (màn hình riêng)
        if IS_WINDOWS:
            os.system("cls")
        else:
            os.system("clear")
        print("=" * 62)
        print("  BƯỚC 6: VÒNG LẶP FLASH")
        print("=" * 62)
        print(f"  Loại ESP : {chip_label(chip_key)}")
        print(f"  Sản phẩm : {product}")
        print(f"  Cổng COM : {port}")
        print(f"  Chế độ   : {'AUTO MULTI FLASH' if mode == 'auto' else 'CONFIRM MULTI FLASH'}")
        print()
        LAST_ERROR = ""
        flashed = 0
        result = None
        while result not in ("exit", "error"):
            result = run_multi_flash(port, mapping, profile, mode)
            # "again" = flash thành công (đang chờ); "exit" = flash thành công rồi thoát
            if result in ("again", "exit"):
                flashed += 1
        if result == "error":
            warn("Vòng flash đã dừng do lỗi.")

        # BƯỚC 7: báo cáo số lượng, rồi đóng cửa sổ
        step7_summary(flashed, LAST_ERROR)
        return 0

    pause_end()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nĐã hủy bởi người dùng (Ctrl+C).")
        pause_end()
        sys.exit(130)
