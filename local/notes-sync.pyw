# PhoneBox: keeps the "Нотатки" page in sync with two text files on this PC.
#   Нотатки.txt  <-> the note on the phone (both ways: edit on the PC or on the phone)
#   Справи.txt    -> the "Справи" checklist (one item per line; ticks are kept on the phone)
# Talks only to the local PhoneBox agent (127.0.0.1:8765).
# To stop it: delete "PhoneBox Notes.lnk" from the Startup folder and end its pythonw.exe.
import http.server, json, os, threading, time, urllib.parse, urllib.request, winreg

AGENT = "http://127.0.0.1:8765"
PAGE, NOTE, TODO = "notes", "note-main", "todo"
LOG = os.path.expandvars(r"%LOCALAPPDATA%\PhoneBox\notes-sync.log")
STATE = os.path.expandvars(r"%LOCALAPPDATA%\PhoneBox\notes-sync.state.json")


def documents():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            path = os.path.expandvars(winreg.QueryValueEx(k, "Personal")[0])
            if os.path.isdir(path):
                return path
    except OSError:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


FOLDER = os.path.join(documents(), "PhoneBox")
NOTE_FILE = os.path.join(FOLDER, "Нотатки.txt")
TODO_FILE = os.path.join(FOLDER, "Справи.txt")


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def read(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read().replace("\r\n", "\n")
    except FileNotFoundError:
        return None


def write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)
    os.replace(tmp, path)


def get_settings():
    with urllib.request.urlopen(AGENT + "/api/settings", timeout=5) as r:
        return json.loads(r.read().decode("utf-8")), r.headers.get("X-Config-Version")


def widget(cfg, wid):
    for p in cfg.get("pages", []):
        if p.get("id") == PAGE:
            for w in p.get("widgets", []):
                if w.get("id") == wid:
                    return w
    return None


def set_note(text, version):
    q = urllib.parse.urlencode({"text": text, "version": version or ""})
    req = urllib.request.Request(f"{AGENT}/api/widget/{PAGE}/{NOTE}/note?{q}", method="POST",
                                 headers={"X-PhoneBox": "1"})
    urllib.request.urlopen(req, timeout=5).read()


def put_settings(cfg, version):
    body = json.dumps(cfg, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(AGENT + "/api/settings", data=body, method="PUT",
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "X-Config-Version": version or ""})
    urllib.request.urlopen(req, timeout=5).read()


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(s):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)


def step(state):
    cfg, version = get_settings()
    note, todo = widget(cfg, NOTE), widget(cfg, TODO)
    if not note:
        return
    phone = (note.get("options") or {}).get("text", "")
    pc = read(NOTE_FILE)
    synced = state.get("note")

    if pc is None:                      # first run: create the file from the phone's note
        write(NOTE_FILE, phone); state["note"] = phone; log("created Нотатки.txt")
    elif pc != synced and phone == synced:
        set_note(pc, version); state["note"] = pc; log("note: PC -> phone")
        cfg, version = get_settings()
    elif phone != synced and pc == synced:
        write(NOTE_FILE, phone); state["note"] = phone; log("note: phone -> PC")
    elif pc != synced and phone != synced and pc != phone:
        # changed on both sides: the PC file wins, the phone's version is kept next to it
        write(os.path.join(FOLDER, time.strftime("Нотатки (з телефона %Y-%m-%d %H-%M).txt")), phone)
        set_note(pc, version); state["note"] = pc; log("note: conflict, PC kept, phone copy saved")
        cfg, version = get_settings()
    elif synced is None:
        state["note"] = pc

    if todo is not None:
        items = [l.strip() for l in (read(TODO_FILE) or "").split("\n") if l.strip()]
        if read(TODO_FILE) is None:
            current = (todo.get("options") or {}).get("items") or []
            write(TODO_FILE, "\n".join(current) + ("\n" if current else "")); log("created Справи.txt")
        else:
            todo = widget(cfg, TODO)
            if (todo.get("options") or {}).get("items") != items:
                todo.setdefault("options", {})["items"] = items
                put_settings(cfg, version); log(f"checklist: {len(items)} items from PC")
    save_state(state)


# ---- browser editor: http://notes.localhost (port 80, or 8780 when 80 is taken) -----------------
UI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes-ui.html")
HOSTS = {"notes.localhost", "localhost", "127.0.0.1"}
file_lock = threading.Lock()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _host_ok(self):
        # refuse other host names (DNS rebinding) and other sites' pages (Origin)
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        if host not in HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin:
            o = urllib.parse.urlsplit(origin)
            if (o.hostname or "").lower() not in HOSTS:
                return False
        return True

    def _api_ok(self):
        # a custom header forces a CORS preflight that this server never answers, so other sites cannot call it
        return self._host_ok() and self.headers.get("X-Notes") == "1"

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        if self.path in ("/", "/index.html"):
            with open(UI_FILE, "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if self.path == "/api/notes" and self._api_ok():
            with file_lock:
                note = read(NOTE_FILE) or ""
                todo = [l.strip() for l in (read(TODO_FILE) or "").split("\n") if l.strip()]
            return self._send(200, {"note": note, "todo": todo})
        self._send(404, {"error": "not found"})

    def do_PUT(self):
        if not self._api_ok() or not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._send(403, {"error": "forbidden"})
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": "bad json"})
        with file_lock:
            if self.path == "/api/note" and isinstance(body.get("text"), str):
                write(NOTE_FILE, body["text"])
            elif self.path == "/api/todo" and isinstance(body.get("items"), list):
                items = [str(s).replace("\n", " ").strip()[:120] for s in body["items"] if str(s).strip()][:100]
                write(TODO_FILE, "\n".join(items) + ("\n" if items else ""))
            else:
                return self._send(404, {"error": "not found"})
        self._send(200, {"ok": True})


def serve():
    for port in (80, 8780):
        try:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            continue
        log(f"editor at http://notes.localhost{'' if port == 80 else ':' + str(port)}")
        srv.serve_forever()
    log("editor: no free port (80, 8780)")


def main():
    os.makedirs(FOLDER, exist_ok=True)
    log(f"started, folder: {FOLDER}")
    threading.Thread(target=serve, daemon=True).start()
    state = load_state()
    while True:
        try:
            with file_lock:
                step(state)
        except Exception as e:
            log(f"sync failed: {type(e).__name__}: {e}")
        time.sleep(2)


if __name__ == "__main__":
    main()
