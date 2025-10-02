from flask import Flask, jsonify, request
import requests, hashlib, os, time
from bs4 import BeautifulSoup
import telegram

app = Flask(__name__)

URL = "https://www.intelligentexistence.com/connect-to-clarity/"
STATE_FILE = "/data/last_hash.txt"
LAST_HTML_FILE = "/data/last_page.html"

# Environment variables from Render dashboard
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
SECRET_KEY = os.getenv("WATCHER_SECRET", "mysecret123")

def notify(msg):
    """Send Telegram alert"""
    if TG_TOKEN and TG_CHAT_ID:
        try:
            bot = telegram.Bot(token=TG_TOKEN)
            bot.send_message(chat_id=TG_CHAT_ID, text=msg[:4000])
        except Exception as e:
            print("Telegram notify failed:", e)

def fetch_page():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PageWatcher/1.0)"}
    r = requests.get(URL, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text

def clean_html(html):
    """Remove countdown timer only"""
    soup = BeautifulSoup(html, "html.parser")
    timer = soup.find("span", {"id": "intelligent-existence-products-countdown"})
    if timer:
        timer.decompose()
    return str(soup)

def compute_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

@app.route("/")
def index():
    """Main watcher endpoint"""
    if request.args.get("secret") != SECRET_KEY:
        return jsonify({"status": "unauthorized"}), 403

    try:
        html = fetch_page()
        cleaned_html = clean_html(html)
        new_hash = compute_hash(cleaned_html)

        old_hash = None
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                old_hash = f.read().strip()

        if old_hash != new_hash:
            notify(f"⚠️ Page changed at {time.strftime('%Y-%m-%d %H:%M:%S')} {URL}")
            with open(STATE_FILE, "w") as f:
                f.write(new_hash)
            with open(LAST_HTML_FILE, "w", encoding="utf-8") as f:
                f.write(cleaned_html)
            return jsonify({"status": "changed"})
        else:
            return jsonify({"status": "no change"})
    except Exception as e:
        notify(f"Watcher Error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/heartbeat")
def heartbeat():
    """Simple health check endpoint"""
    return jsonify({"status": "ok", "time": time.strftime("%Y-%m-%d %H:%M:%S")})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))