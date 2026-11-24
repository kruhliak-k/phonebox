# PhoneBox: forwards Telegram Desktop's Windows notifications to the phone panel.
# Reads the Windows notification database (read-only) every 2 seconds and posts each new
# Telegram notification to the local PhoneBox agent (POST http://127.0.0.1:8765/api/notify).
# Nothing leaves this computer except to the phone through PhoneBox.
# To stop it: delete "PhoneBox Telegram.lnk" from the Startup folder and end pythonw.exe.
import json, os, re, sqlite3, time, urllib.request
import xml.etree.ElementTree as ET

DB = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db")
AGENT = "http://127.0.0.1:8765/api/notify"
QUERY = ("select n.\"Order\", n.Payload from Notification n "
         "join NotificationHandler h on h.RecordId = n.HandlerId "
         "where lower(h.PrimaryId) like '%telegram%' and n.\"Order\" > ? order by n.\"Order\"")


def connect():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)


def texts(payload):
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    try:
        root = ET.fromstring(payload)
        parts = [t.text.strip() for t in root.iter("text") if t.text and t.text.strip()]
    except ET.ParseError:
        parts = [s.strip() for s in re.findall(r"<text[^>]*>([^<]*)</text>", payload) if s.strip()]
    return parts


def send(title, text):
    body = json.dumps({"title": title[:80], "text": text[:300], "level": "info", "vibrate": True}).encode("utf-8")
    req = urllib.request.Request(AGENT, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    urllib.request.urlopen(req, timeout=5).read()


LOG = os.path.expandvars(r"%LOCALAPPDATA%\PhoneBox\telegram-bridge.log")


def log(msg):
    # only order numbers and errors, never message text
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def main():
    log("bridge started")
    last = None
    while True:
        try:
            with connect() as con:
                if last is None:
                    last = con.execute("select coalesce(max(\"Order\"), 0) from Notification").fetchone()[0]
                for order, payload in con.execute(QUERY, (last,)).fetchall():
                    last = max(last, order)
                    parts = texts(payload)
                    if not parts:
                        continue
                    title = parts[0]
                    text = " · ".join(parts[1:]) or "Нове повідомлення"
                    try:
                        send("✈ " + title, text)
                        log(f"forwarded notification {order}")
                    except Exception as e:
                        log(f"send failed for {order}: {type(e).__name__}: {e}")
        except Exception as e:
            log(f"database read failed: {type(e).__name__}: {e}")
        time.sleep(2)


if __name__ == "__main__":
    main()
