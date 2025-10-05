from flask import Flask, jsonify, request
import requests, hashlib, os, time, shutil
from bs4 import BeautifulSoup
import cloudscraper
import telegram
import difflib
import re
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

URL = "https://www.intelligentexistence.com/connect-to-clarity/"

INIT_DIR = "init"
if os.path.exists("/data"):
    DATA_DIR = "/data"   # Render
else:
    DATA_DIR = "data"    # Local

STATE_FILE = os.path.join(DATA_DIR, "last_hash.txt")
LAST_HTML_FILE = os.path.join(DATA_DIR, "last_page.html")

INIT_STATE_FILE = os.path.join(INIT_DIR, "last_hash.txt")
INIT_HTML_FILE = os.path.join(INIT_DIR, "last_page.html")

# Copy init files to data directory if they don't exist
if os.path.exists(INIT_STATE_FILE) and not os.path.exists(STATE_FILE):
    shutil.copy2(INIT_STATE_FILE, STATE_FILE)
    logger.info(f"Copied initial state file to {STATE_FILE}")

if os.path.exists(INIT_HTML_FILE) and not os.path.exists(LAST_HTML_FILE):
    shutil.copy2(INIT_HTML_FILE, LAST_HTML_FILE)
    logger.info(f"Copied initial HTML file to {LAST_HTML_FILE}")

# Environment variables from Render dashboard
TG_TOKEN = os.getenv("TG_TOKEN", "8178146691:AAGRjObZRRFmkmKBJ7GOK_zBeCBLGdiIn8U")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "-1002930872699")
SECRET_KEY = os.getenv("WATCHER_SECRET", "ie_929")

def diff_pages(old, new, max_lines=50):
    diff = difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile="old",
        tofile="new",
        lineterm=""
    )
    diff_text = "\n".join(diff)
    # Limit size so Telegram doesn’t reject (max ~4000 chars)
    return "\n".join(diff_text.splitlines()[:max_lines])

async def notify(msg):
    """Send Telegram alert"""
    if TG_TOKEN and TG_CHAT_ID:
        try:
            bot = telegram.Bot(token=TG_TOKEN)
            logger.info("Sending Telegram notification...")
            await bot.send_message(chat_id=TG_CHAT_ID, text=msg[:4000])
            logger.info("Telegram notification sent successfully")
        except Exception as e:
            logger.error(f"Telegram notify failed: {str(e)}", exc_info=True)

def fetch_page():
    scraper = cloudscraper.create_scraper(
        browser={
            "custom": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        }
    )
    try:
        logger.info(f"Fetching page: {URL}")
        r = scraper.get(URL, timeout=30, proxies=None)
        r.raise_for_status()
        logger.info(f"Page fetched successfully: {r.status_code}")
        return r.text
    except Exception as e:
        logger.error(f"Failed to fetch page: {str(e)}", exc_info=True)
        return None

def clean_html(html):
    soup = BeautifulSoup(html, "html.parser")

    # remove countdown timer
    timer = soup.find("span", {"id": "intelligent-existence-products-countdown"})
    if timer:
        timer.decompose()

    # remove scripts, styles, noscript
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # remove meta tags
    for meta in soup.find_all("meta"):
        meta.decompose()

    cleaned = soup.prettify()

    # remove W3 Total Cache footer comments (dynamic noise)
    cleaned = re.sub(
        r'<!--\s*Performance optimized by W3 Total Cache.*?-->',
        '',
        cleaned,
        flags=re.DOTALL
    )

    return cleaned.strip()

def compute_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

@app.route("/")
async def index():
    """Main watcher endpoint"""
    if request.args.get("secret") != SECRET_KEY:
        logger.warning(f"Unauthorized access attempt from IP: {request.remote_addr}")
        return jsonify({"status": "unauthorized"}), 403

    try:
        html = fetch_page()
        if html is None:
            raise Exception("Failed to fetch page content")
            
        cleaned_html = clean_html(html)
        new_hash = compute_hash(cleaned_html)
        logger.info(f"New page hash: {new_hash}")

        old_hash = None
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    old_hash = f.read().strip()
                logger.debug(f"Old hash from file: {old_hash}")
            except Exception as e:
                logger.error(f"Error reading state file: {str(e)}", exc_info=True)

        if old_hash != new_hash:
            logger.info("Page change detected")
            diff_text = ""
            if os.path.exists(LAST_HTML_FILE):
                try:
                    with open(LAST_HTML_FILE, "r", encoding="utf-8") as f:
                        old_cleaned = f.read()
                    diff_text = diff_pages(old_cleaned, cleaned_html, max_lines=40)
                except Exception as e:
                    logger.error(f"Error generating diff: {str(e)}", exc_info=True)

            alert_msg = f"⚠️ Page changed at {time.strftime('%Y-%m-%d %H:%M:%S')}\n{URL}"
            if diff_text:
                alert_msg += f"\n\nDiff preview:\n{diff_text}"

            await notify(alert_msg)

            try:
                with open(STATE_FILE, "w") as f:
                    f.write(new_hash)
                with open(LAST_HTML_FILE, "w", encoding="utf-8") as f:
                    f.write(cleaned_html)
                logger.info("State files updated successfully")
            except Exception as e:
                logger.error(f"Error updating state files: {str(e)}", exc_info=True)

            return jsonify({"status": "Changed"})
        else:
            logger.debug("No changes detected")
            return jsonify({"status": "Not Changed"})
    except Exception as e:
        logger.error(f"Watcher error: {str(e)}", exc_info=True)
        await notify(f"Watcher Error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/heartbeat")
def heartbeat():
    """Simple health check endpoint"""
    return jsonify({"status": "ok", "time": time.strftime("%Y-%m-%d %H:%M:%S")})

@app.get("/send-test-message")
async def test():
    bot = telegram.Bot(token=TG_TOKEN)
    await bot.send_message(chat_id=TG_CHAT_ID, text="✅ Test message from Page Watcher!")
    return jsonify({"status": "ok", "message": "Telegram message sent"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))