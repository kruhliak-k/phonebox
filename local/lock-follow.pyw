# PhoneBox: the phone follows the computer.
# Windows locked or the monitor turned off  -> the phone screen goes off.
# Windows unlocked and the monitor is on    -> the phone wakes and opens the PhoneBox panel.
# Listens for Windows events (session lock/unlock, console display state) in a hidden window
# and drives the phone over adb. Needs "USB debugging (Security settings)" on Xiaomi phones.
# To stop it: delete "PhoneBox Lock.lnk" from the Startup folder and end its pythonw.exe.
import ctypes, glob, os, subprocess, threading, time, uuid
from ctypes import wintypes

LOG = os.path.expandvars(r"%LOCALAPPDATA%\PhoneBox\lock-follow.log")
PACKAGE = "net.oxog.phonebox.deskpanel/.MainActivity"


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def find_adb():
    hits = glob.glob(os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Google.PlatformTools*\platform-tools\adb.exe"))
    hits += [os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")]
    return next((h for h in hits if os.path.exists(h)), "adb")


ADB = find_adb()
NO_WINDOW = 0x08000000


def adb(*args, timeout=8):
    try:
        r = subprocess.run([ADB, *args], capture_output=True, text=True, timeout=timeout,
                           creationflags=NO_WINDOW)
        return r.stdout
    except Exception as e:
        log(f"adb {args[:3]} failed: {type(e).__name__}")
        return ""


def phones():
    out = adb("devices")
    return [l.split("\t")[0] for l in out.splitlines()[1:]
            if l.endswith("\tdevice") and not l.startswith("emulator-") and ":" not in l.split("\t")[0]]


def phone_off():
    for s in phones():
        if "mWakefulness=Awake" in adb("-s", s, "shell", "dumpsys power | grep mWakefulness="):
            adb("-s", s, "shell", "input", "keyevent", "223")
            log(f"phone {s}: screen off")


def phone_on():
    for s in phones():
        adb("-s", s, "shell", "input", "keyevent", "224")
        time.sleep(0.8)
        secure = "secure=true" in adb("-s", s, "shell", "dumpsys window | grep -m1 -o 'secure=[a-z]*'")
        if not secure:
            adb("-s", s, "shell", "wm", "dismiss-keyguard")
        adb("-s", s, "shell", "am", "start", "-n", PACKAGE)
        log(f"phone {s}: woken" + (" (lock screen is secured: unlock it on the phone)" if secure else ""))


# ---- Windows events ---------------------------------------------------------------------------
user32 = ctypes.WinDLL("user32", use_last_error=True)
wtsapi = ctypes.WinDLL("wtsapi32")

WM_POWERBROADCAST, PBT_POWERSETTINGCHANGE = 0x0218, 0x8013
WM_HOTKEY, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0312, 0x1, 0x2, 0x4000
WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 0x02B1, 0x7, 0x8
GUID_CONSOLE_DISPLAY_STATE = uuid.UUID("6FE69556-704A-47A0-8F24-C28D936FDA47")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [("PowerSetting", GUID), ("DataLength", wintypes.DWORD), ("Data", ctypes.c_ubyte * 1)]


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
kernel32 = ctypes.WinDLL("kernel32")
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
wtsapi.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
user32.RegisterPowerSettingNotification.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), wintypes.DWORD]

state = {"locked": False, "display": True}
lock = threading.Lock()
last = {"want": "on"}


def apply():
    want = "on" if (not state["locked"] and state["display"]) else "off"
    with lock:
        if want == last["want"]:
            return
        last["want"] = want
    log(f"computer {'locked' if state['locked'] else 'unlocked'}, display {'on' if state['display'] else 'off'} -> phone {want}")
    threading.Thread(target=phone_on if want == "on" else phone_off, daemon=True).start()


@WNDPROC
def wndproc(hwnd, msg, wparam, lparam):
    if msg == WM_HOTKEY:
        # only the LEFT Alt, so AltGr (Right Alt) + arrows keeps doing what it did
        test = os.path.exists(os.path.join(os.path.dirname(LOG), "hotkey-test"))
        lalt = bool(user32.GetAsyncKeyState(VK_LMENU) & 0x8000)
        if test:
            log(f"TEST hotkey id={wparam} left_alt={lalt}")
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK if wparam == 1 else winsound.MB_OK)
            return 0
        if True:  # any Ctrl+Alt+arrow (some keyboards don't report the left Alt separately)
            # PhoneBox flips pages with the volume keys in the app itself, whatever has focus in the page:
            # volume down = next page, volume up = previous page
            flips.put("25" if wparam == 1 else "24")
            log("hotkey: " + ("next" if wparam == 1 else "previous") + " page")
        return 0
    if msg == WM_WTSSESSION_CHANGE:
        if wparam == WTS_SESSION_LOCK:
            state["locked"] = True; apply()
        elif wparam == WTS_SESSION_UNLOCK:
            state["locked"] = False; apply()
    elif msg == WM_POWERBROADCAST and wparam == PBT_POWERSETTINGCHANGE and lparam:
        s = ctypes.cast(lparam, ctypes.POINTER(POWERBROADCAST_SETTING)).contents
        if bytes(s.PowerSetting) == GUID_CONSOLE_DISPLAY_STATE.bytes_le:
            value = ctypes.cast(ctypes.addressof(s.Data), ctypes.POINTER(wintypes.DWORD)).contents.value
            state["display"] = value != 0  # 0 off, 1 on, 2 dimmed
            apply()
        return 1
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


# ---- hotkeys: Left Ctrl + Left Alt + Left/Right arrow flips the phone's pages ---------------------
VK_LEFT, VK_RIGHT, VK_LCONTROL, VK_LMENU = 0x25, 0x27, 0xA2, 0xA4
VK_RCONTROL, VK_MENU, VK_SHIFT = 0xA3, 0x12, 0x10
WH_KEYBOARD_LL, WM_KEYDOWN, WM_SYSKEYDOWN = 13, 0x0100, 0x0104


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.GetAsyncKeyState.restype = ctypes.c_short

import queue
flips = queue.Queue()


def flipper():
    while True:
        key = flips.get()
        log("hotkey: " + ("next" if key == "25" else "previous") + " page")
        for s in phones():
            adb("-s", s, "shell", "input", "keyevent", key)


def down(vk):
    return user32.GetAsyncKeyState(vk) & 0x8000


@HOOKPROC
def keyhook(code, wparam, lparam):
    if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
        k = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        # RIGHT Ctrl + Left/Right arrow (without Alt or Shift); the left Ctrl keeps its usual word jumps
        if (k.vkCode in (VK_LEFT, VK_RIGHT) and down(VK_RCONTROL) and not down(VK_LCONTROL)
                and not down(VK_MENU) and not down(VK_SHIFT)):
            flips.put("25" if k.vkCode == VK_RIGHT else "24")  # volume down / up: next / previous page
            return 1  # swallow it, so the app in front doesn't get Ctrl+arrow
    return user32.CallNextHookEx(None, code, wparam, lparam)


def main():
    log(f"started (adb: {ADB})")
    threading.Thread(target=flipper, daemon=True).start()
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASS(lpfnWndProc=wndproc, hInstance=hinst, lpszClassName="PhoneBoxLockFollow")
    user32.RegisterClassW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(0, "PhoneBoxLockFollow", "PhoneBoxLockFollow", 0, 0, 0, 0, 0, None, None, hinst, None)
    wtsapi.WTSRegisterSessionNotification(hwnd, 0)  # NOTIFY_FOR_THIS_SESSION
    g = GUID.from_buffer_copy(GUID_CONSOLE_DISPLAY_STATE.bytes_le)
    user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(g), 0)  # DEVICE_NOTIFY_WINDOW_HANDLE
    # Right Ctrl + arrows need a keyboard hook: Windows hotkeys can't tell the right Ctrl from the left one
    hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, keyhook, kernel32.GetModuleHandleW(None), 0)
    log(f"hotkeys Right Ctrl + arrows: {'on' if hook else 'FAILED, error ' + str(ctypes.get_last_error())}")
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    main()
