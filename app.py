"""Automation core for leofame.com's free TikTok views.

Handles sign-in (automatic), the account balance and the free-views requests. It knows
nothing about the UI: ui.py drives an `Automation` object and run.py wires both together.
The requests mirror what the site's own pages do (see the HAR captures in ./network).
"""
import base64
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

BASE = "https://leofame.com"
LOGIN_PATH = "/login"
SIGN_IN_PATH = "/auth/ajax_sign_in"
FREE_VIEWS_PATH = "/free-tiktok-views"
ORDERS_PATH = "/dashboard/orders"
ORDER_STATUSES = ("all", "pending", "processing", "completed", "canceled")
ORDER_SEARCH_TYPES = ("1", "3")  # 1 = Order ID, 3 = Order link (the site's own search options)
CANCEL_WAIT = 18                 # seconds to wait for leofame.com to finish a cancellation
LOG_FILE = "actions.log"
# What a browser sends when it follows a link (the site's Cancel button navigates to its cancel URL).
_NAV_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin", "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
)

# The free form shows a progress bar that runs ~50s (2% per second) before it POSTs.
FORM_WAIT_SECONDS = 50
DEFAULT_QUANTITIES = list(range(100, 201, 4))
HISTORY_LIMIT = 500

# Settings, session cookies, history and the app-window profile live outside the workspace.
DATA_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "Viewdesk"

TIKTOK_LINK_RE = re.compile(r"^https?://([\w-]+\.)?tiktok\.com/\S+$", re.I)
_TOKEN_RE = re.compile(r'name="token"\s+value="([0-9a-fA-F]+)"')
_TOKEN_VAR_RE = re.compile(r"var\s+token\s*=\s*'([0-9a-fA-F]+)'")
_BALANCE_RE = re.compile(r'id="balance-txt"[^>]*>\s*([^<]*?)\s*<')
_AMOUNT_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_QUANTITY_SELECT_RE = re.compile(r'<select[^>]*name="quantity"[^>]*>(.*?)</select>', re.S)
_OPTION_RE = re.compile(r'<option\s+value="(\d+)"')
_TAG_RE = re.compile(r"<[^>]+>")
_ORDER_TAB_RE = re.compile(r'<a\b[^>]*?href="[^"]*/dashboard/orders/(\w+)"[^>]*>((?:(?!</a>).)*)</a>', re.S)
_WIDTH_RE = re.compile(r"width:\s*(\d+(?:\.\d+)?)%")

# -- buying views (order flow) -----------------------------------------------
BUY_PATH = "/buy-tiktok-views"
CUSTOM_ITEM_ID = "132"         # the site sells custom quantities through its smallest package
CARD_MINIMUM = 5.0             # the site's own checkout script: cards are charged at least $5
PREPARED_TTL = 8 * 60          # a verified post stays usable for this many seconds
CATALOG_TTL = 15 * 60          # how long the package list is reused
_TT_HOSTS = {"tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}
_TT_VIDEO_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9._]*)/(?:video|photo)/([0-9]+)", re.I)
_TT_SHORT_RE = re.compile(r"tiktok\.com/(?:t/)?[A-Za-z0-9._]+", re.I)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PANE_RE = re.compile(r'<div class="tab-pane[^"]*" id="hq(\d+)" role="tabpanel">.*?id="myamount">\s*([\d.]+)\s*</div>.*?data-id="(\d+)"', re.S)
_SAVE_RE = re.compile(r'<li class="nav-item Followers-(\d+)">\s*<a class="nav-link px-0 border-0 ?(best)? ?"[^>]*>\s*<h3>[\d,]+</h3>\s*<p>([^<]*)</p>', re.S)
_CUSTOM_RE = re.compile(r'id="custom_quantity"[^>]*min="(\d+)"[^>]*max="(\d+)"')
_PRICES_RE = re.compile(r"var\s+prices\s*=\s*(\{.*?\})\s*;", re.S)
_DELIVERY_RE = re.compile(r"items_delivery_speed\s*=\s*(\{.*?\})\s*;", re.S)
_ITEMS_RE = re.compile(r"data:\s*(\[\{.*?\}\])\s*,", re.S)
_MAIL_FIELD_RE = re.compile(r'name="email"[^>]*?value="([^"]*)"')
_USERNAME_FIELD_RE = re.compile(r'<input[^>]*name="username"[^>]*>')
_ACCOUNT_IMAGE_RE = re.compile(r'class="account-image"\s+src="([^"]+)"')
_CHECKOUT_ITEM_RE = re.compile(r"<strong>\s*([\d,]+)\s+TikTok Views\s*</strong>")
_CHECKOUT_USER_RE = re.compile(r'class="account-action">\s*<span>@?([^<]+)</span>')
_CHECKOUT_SPLIT_RE = re.compile(r"[\d,]+\s+Views per\s+(\d+)\s+Posts?", re.I)
_TOTAL_RE = re.compile(r'id="total-pay">\s*([\d.]+)\s*<')
_HIDDEN_RE = re.compile(r'<input type="hidden" name="(\w+)" value="([^"]*)"')
_GATEWAY_RE = re.compile(r'name="gateway_id"[^>]*value="(\d+)"[^>]*>\s*<label[^>]*>.*?<strong>(.*?)</strong>', re.S)
_GATEWAY_HOST_RE = re.compile(r"""https?://([A-Za-z0-9.-]+\.gateway\.mastercard\.com)(?=[/:?#'"\s\\]|$)""", re.I)
_GATEWAY_URL_RE = re.compile(r"https://[A-Za-z0-9.-]+\.gateway\.mastercard\.com/[^\s\"'<>\\)]+", re.I)
_TRX_RE = re.compile(r"payment_response[^\"'\s<>]*?trx_id=(\d+)", re.I)
_GATEWAY_SESSION_RE = re.compile(r"\b(SESSION[0-9A-Za-z]{10,})\b")


class LeoFameError(Exception):
    """Raised for network problems and for errors reported by the site."""

    def __init__(self, message, network=False, details=""):
        super().__init__(message)
        self.network = network
        self.details = details      # technical facts (HTTP status, what the site answered) for the "details" fold-out


def _clean_message(message):
    message = _TAG_RE.sub("", str(message or "")).replace("\\'", "'")
    return " ".join(message.split())


def _site_message(response):
    """The success text of a JSON reply from the site; raises LeoFameError when it reports an error."""
    try:
        data = json.loads(response.text.strip())
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    if data.get("error"):
        raise LeoFameError(_clean_message(data["error"]))
    return _clean_message(data.get("success") or data.get("message") or "")


def _local_timezone():
    """Same fallback the site's own script uses when the browser has no IANA zone."""
    offset = datetime.now().astimezone().utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset else 0
    sign = "+" if minutes >= 0 else "-"
    hours, mins = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{mins:02d}"


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_tiktok_link(link):
    """Return what the site's order form sends as `username` for a post link, or raise ValueError.

    Mirrors the site's own extractInfo(): a video/photo link is sent as its numeric id,
    a short link (vm./vt./tiktok.com/t/...) as the whole URL. Profiles are not accepted.
    """
    link = str(link or "").strip()
    if link and "://" not in link:
        link = "https://" + link
    parts = urlsplit(link)
    if (parts.hostname or "").lower() not in _TT_HOSTS:
        raise ValueError("Paste the link of a TikTok video (tiktok.com).")
    match = _TT_VIDEO_RE.search(link)
    if match:
        return match.group(2)
    if _TT_SHORT_RE.search(link) and "/@" not in parts.path:
        return link
    raise ValueError("Paste the link of a specific TikTok video, not a profile.")


def _link_search_term(query):
    """The site matches "Order link" searches against the link as it stored it (with www., no trailing slash),
    while its own table shows the link in another form. A pasted TikTok link is therefore reduced to the
    part that always matches: the video id (or the @account)."""
    video = _TT_VIDEO_RE.search(query)
    if video:
        return video.group(2)
    account = re.search(r"tiktok\.com/@([A-Za-z0-9._]+)", query, re.I)
    return account.group(1) if account else query.strip()


def _delivery_options(raw):
    """The site's delivery-speed map ({'2': '2&nbsp;hours (Recommended)', ...}) as a clean list."""
    options = []
    for value, label in (raw or {}).items():
        text = " ".join(unescape(label).replace("\xa0", " ").split())
        match = re.match(r"^(.*?)\s*\(([^)]*)\)$", text)
        name, hint = (match.group(1), match.group(2)) if match else (text, "")
        options.append({"value": str(value), "label": name, "hint": hint, "recommended": hint.lower() == "recommended"})
    return options


def _price(text):
    match = _AMOUNT_RE.search(str(text or ""))
    return float(match.group(0).replace(",", "")) if match else 0.0


def _post_info(post):
    """One post from the site's listing, reduced to what the UI needs. `key` is what the order form sends."""
    post_id = str(post.get("id") or "")
    code = str(post.get("media_code") or post_id)
    return {
        "key": f"{code}:{post_id}" if post_id else "",
        "id": post_id,
        "link": post.get("link") or "",
        "thumbnail": post.get("thumbnail_url") or post.get("thumbnail") or "",
        "views": post.get("views"), "likes": post.get("likes"),
        "comments": post.get("comments"), "shares": post.get("shares"),
        "created": post.get("created") or "",
        "pinned": bool(post.get("is_pinned")),
        "type": post.get("type") or "video",
        "private": bool(post.get("private")),
    }


def find_payment_url(text):
    """The Mastercard hosted-checkout address from the site's answer: its own URL, used exactly as it gives it.

    The checkout page also links to the gateway's script files, so only an address that carries the payment
    session counts. If the site names the session without a full address, we build the gateway's entry URL.
    """
    text = unescape(str(text or "").replace("\\/", "/"))
    for match in _GATEWAY_URL_RE.finditer(text):
        url = match.group(0).rstrip("\"'\\,;)")
        if _GATEWAY_SESSION_RE.search(url):
            return url
    host = _GATEWAY_HOST_RE.search(text)
    session = _GATEWAY_SESSION_RE.search(text)
    if not (host and session):
        return None
    return f"https://{host.group(1).lower()}/checkout/entry/{session.group(1)}?checkoutVersion=1.0.0"


def find_transaction_id(text):
    """leofame.com's own payment number, when its answer carries the address the card page returns to."""
    found = _TRX_RE.search(unescape(str(text or "").replace("\\/", "/")))
    return found.group(1) if found else ""


def _safe_url(url):
    """A payment address for the log: the session id is shortened, so a log file is never a usable payment link."""
    return re.sub(r"(SESSION[0-9A-Za-z]{4})[0-9A-Za-z]+([0-9A-Za-z]{4})", r"\1…\2", str(url or ""))


_VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "area", "base", "col", "embed", "source", "wbr"}
_TONES = (("success", "ok"), ("warning", "warn"), ("danger", "err"), ("info", "info"), ("primary", "info"), ("secondary", "muted"))
_CALL_RE = re.compile(r"\s*(\w+)\((.*)\)\s*;?\s*$", re.S)
_QUOTED_RE = re.compile(r"\"([^\"]*)\"|'([^']*)'")
_ITEM_ID_RE = re.compile(r"[?&]item_id=(\d+)")


def _tone(classes):
    """ok / warn / err / info / muted from the bootstrap colour classes the site puts on badges and buttons."""
    joined = " ".join(classes)
    return next((tone for key, tone in _TONES if key in joined), "")


def _parse_call(onclick):
    """`cancel_order("abc")` -> ("cancel_order", ["abc"])."""
    match = _CALL_RE.match(onclick or "")
    if not match:
        return "", []
    return match.group(1), [a or b for a, b in _QUOTED_RE.findall(match.group(2))]


def _site_path(href):
    """The path (+query) of a link into the account area of leofame.com, else None."""
    parts = urlsplit(str(href or ""))
    if parts.netloc not in ("", "leofame.com", "www.leofame.com"):
        return None
    if not (parts.path.startswith("/dashboard/") or parts.path.startswith("/order/")):
        return None
    return parts.path + (f"?{parts.query}" if parts.query else "")


class _CellParts(HTMLParser):
    """The inside of one table cell: title, list items, buttons/links, badges and images."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.items, self.actions, self.badges, self.images = "", [], [], [], []
        self._stack, self._h6, self._li = [], False, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        target = None
        if tag == "h6":
            self._h6 = True
        elif tag == "li":
            self._li = {"text": "", "href": ""}
            self.items.append(self._li)
        elif tag in ("a", "button"):
            href = a.get("href") or ""
            href = "" if href == "#" else href
            if href or a.get("onclick"):
                target = {"tag": tag, "text": "", "href": href, "onclick": a.get("onclick") or "", "classes": cls, "icon": ""}
                self.actions.append(target)
                if self._li is not None and href and not self._li["href"]:
                    self._li["href"] = href
        elif tag == "span" and "badge" in cls:
            target = {"text": "", "classes": cls}
            self.badges.append(target)
        elif tag == "img":
            self.images.append({"alt": a.get("alt") or "", "src": a.get("src") or ""})
        elif tag == "i":
            for _, open_target in reversed(self._stack):
                if open_target is not None and "icon" in open_target:
                    open_target["icon"] = " ".join(cls)
                    break
        if tag not in _VOID_TAGS:
            self._stack.append((tag, target))

    def handle_endtag(self, tag):
        if tag == "h6":
            self._h6 = False
        elif tag == "li":
            self._li = None
        for i in range(len(self._stack) - 1, -1, -1):   # stray end tags such as </br> are simply ignored
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        if self._h6:
            self.title += data
        if self._li is not None:
            self._li["text"] += data
        for _, target in self._stack:
            if target is not None:
                target["text"] += data


class _OrdersPage(HTMLParser):
    """Reads a table (and its pagination) out of a dashboard page: orders, billing, ...

    The columns are taken from the table's own header row. The site leaves out most `</tr>` tags,
    so a new <tr>/<td> (or the end of the table) also closes whatever is still open.
    """

    _BLOCKS = {"br", "div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self, anywhere=False):
        super().__init__(convert_charrefs=True)
        self.headers, self.rows, self.pages = [], [], []
        self._region = anywhere     # inside #result_ajaxSearch (or anywhere, for pages without it)
        self._table = 0             # 0 not seen, 1 inside, 2 finished
        self._section = ""
        self._row = None
        self._cell = None
        self._pag = None            # [tag, depth] of the pagination container
        self._item = None
        self._solo = False          # pagination item without an <li> (bare <a>/<strong>)

    # -- tags ----------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if a.get("id") == "result_ajaxSearch":
            self._region = True
        if not self._region:
            return
        if self._pag:
            if tag == self._pag[0]:
                self._pag[1] += 1
            self._pagination_start(tag, a, cls)
        elif any("pagination" in c for c in cls):
            self._pag = [tag, 1]
        if tag == "table" and self._table == 0:
            self._table = 1
        elif self._table == 1:
            self._table_start(tag, a, cls)

    def handle_endtag(self, tag):
        if not self._region:
            return
        if self._cell is not None and tag in self._BLOCKS:
            self._cell["parts"].append("\n")
        if self._pag:
            if tag == "li" or (self._solo and tag in ("a", "strong")):
                self._finish_item()
            if tag == self._pag[0]:
                self._pag[1] -= 1
                if self._pag[1] == 0:
                    self._pag = None
        if self._table != 1:
            return
        if tag in ("td", "th"):
            self._finish_cell()
        elif tag == "tr":
            self._close_row()
        elif tag in ("thead", "tbody"):
            self._close_row()
            self._section = ""
        elif tag == "table":
            self._close_row()
            self._table = 2
        elif self._cell is not None:
            self._cell["p"].handle_endtag(tag)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["parts"].append(data)
            self._cell["p"].handle_data(data)
        elif self._item is not None:
            self._item["label"] += data

    # -- table ---------------------------------------------------------------

    def _table_start(self, tag, a, cls):
        if tag in ("thead", "tbody"):
            self._close_row()
            self._section = tag
        elif tag == "tr":
            self._close_row()
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._finish_cell()
            self._cell = {"parts": [], "classes": [], "progress": None, "th": tag == "th", "p": _CellParts()}
        elif self._cell is not None:
            cell = self._cell
            if tag in self._BLOCKS:
                cell["parts"].append("\n")
            cell["classes"] += cls
            value = a.get("aria-valuenow") or a.get("data-progress")
            match = _WIDTH_RE.search(a.get("style") or "")
            if value is None and match and "progress-bar" in cls:
                value = match.group(1)
            try:
                if value is not None and float(value) > 0:
                    cell["progress"] = min(100, round(float(value)))
            except ValueError:
                pass
            cell["p"].handle_starttag(tag, list(a.items()))

    def _close_row(self):
        self._finish_cell()
        self._finish_row()

    def _finish_cell(self):
        if self._cell is None:
            return
        cell, self._cell = self._cell, None
        norm = lambda s: " ".join(str(s).split())
        lines = ("".join(cell.pop("parts"))).split("\n")
        cell["lines"] = [line for line in (norm(l) for l in lines) if line]
        cell["classes"] = list(dict.fromkeys(cell["classes"]))
        parts = cell.pop("p")
        cell["title"] = norm(parts.title)
        cell["items"] = [{"text": norm(i["text"]), "href": i["href"]} for i in parts.items if norm(i["text"])]
        cell["actions"] = [{**x, "text": norm(x["text"])} for x in parts.actions]
        cell["badges"] = [{"text": norm(b["text"]), "classes": b["classes"]} for b in parts.badges if norm(b["text"])]
        cell["images"] = parts.images
        cell["links"] = [x["href"] for x in cell["actions"] if x["href"]]
        self._row.append(cell)

    def _finish_row(self):
        if self._row is None:
            return
        row, self._row = self._row, None
        if not row:
            return
        if self._section == "thead" or (not self.headers and all(c["th"] for c in row)):
            self.headers = [" ".join(c["lines"]) for c in row]
        else:
            self.rows.append([{k: v for k, v in c.items() if k != "th"} for c in row])

    # -- pagination ----------------------------------------------------------

    def _pagination_start(self, tag, a, cls):
        if tag == "li":
            self._item, self._solo = {"label": "", "url": None, "active": "active" in cls, "disabled": "disabled" in cls}, False
        elif tag in ("a", "strong") and self._item is None:
            self._item, self._solo = {"label": "", "url": None, "active": tag == "strong", "disabled": False}, True
        if tag == "a" and self._item is not None and a.get("href") and a["href"] != "#":
            self._item["url"] = a["href"]

    def _finish_item(self):
        item, self._item, self._solo = self._item, None, False
        if item and item["label"].strip():
            item["label"] = " ".join(item["label"].split())
            self.pages.append(item)


def _build_orders(headers, rows):
    """Structured orders from the orders table (columns are found by their header names).

    Each order carries everything the site shows: service, quantity/link/remains/transaction facts,
    price, status, created time, the notes in the Action column and the buttons the site offers.
    `_raw` keeps the site's own button calls for the server; it is never sent to the browser.
    """
    def col(*patterns):
        return next((i for i, h in enumerate(headers) if any(re.search(p, h, re.I) for p in patterns)), None)

    idx = {"no": col(r"^no\.?$"), "id": col(r"order id"), "details": col(r"detail"), "price": col(r"price|amount"),
           "status": col(r"status"), "created": col(r"created|date"), "action": col(r"action")}
    if idx["id"] is None or idx["details"] is None:
        return []
    blank = {"lines": [], "classes": [], "items": [], "actions": [], "badges": [], "title": "", "images": [], "links": []}
    orders = []
    for row in rows:
        def cell(name):
            i = idx[name]
            return row[i] if i is not None and i < len(row) else blank
        order_id = next(iter(re.findall(r"\d+", " ".join(cell("id")["lines"]))), "")
        if not order_id:
            continue
        details, status, action = cell("details"), cell("status"), cell("action")
        facts, quantity, link = [], None, ""
        for item in details["items"]:
            label, _, value = item["text"].partition(":")
            label, value = label.strip(), value.strip()
            fact = {"label": label, "value": value}
            low = label.lower()
            if low == "link":
                link = value
                fact["url"] = value if value.lower().startswith("http") else ""
            elif "transaction" in low and _site_path(item["href"]):
                fact["payment"] = True
            elif low == "quantity":
                digits = re.sub(r"\D", "", value.split()[0]) if value else ""
                quantity = int(digits) if digits else None
            facts.append(fact)
        remains = next((f["value"] for f in facts if f["label"].lower() == "remains"), "")
        progress = None
        if quantity and remains.strip().isdigit():
            progress = max(0, min(100, round((quantity - int(remains)) / quantity * 100)))
        reorder = next((a for a in details["actions"] if "/order/select" in a["href"]), None)
        item_id = (_ITEM_ID_RE.search(reorder["href"]) or [None, ""])[1] if reorder else ""

        actions, raw_actions = [], []
        for act in action["actions"]:
            fn, args = _parse_call(act["onclick"])
            if fn == "cancel_order":
                kind, default = "cancel", "Cancel Order"
            elif fn == "refund_order":
                kind, default = "refund", "Request refund"
            elif fn == "dialog_box":
                kind, default = "info", "Info"
            elif act["href"] and _site_path(act["href"]):
                kind, default = "link", "Open"
            else:
                continue
            entry = {"kind": kind, "label": act["text"] or default}
            if kind == "info":
                entry["text"] = args[1] if len(args) > 1 else ""
            actions.append(entry)
            raw_actions.append({"kind": kind, "args": args, "href": act["href"]})

        orders.append({
            "id": order_id, "no": " ".join(cell("no")["lines"]),
            "service": details["title"] or (details["lines"] or [""])[0],
            "item_id": item_id, "quantity": quantity, "link": link, "facts": facts, "progress": progress,
            "price": " ".join(cell("price")["lines"]),
            "status": {"text": " ".join(status["lines"]), "tone": _tone(status["classes"])},
            "created": " ".join(cell("created")["lines"]),
            "notes": [{"text": b["text"], "tone": _tone(b["classes"])} for b in action["badges"]],
            "actions": actions, "_raw": {"actions": raw_actions},
        })
    return orders


def _build_payments(headers, rows):
    """The account's payments from the billing table. One payment (transaction) can cover several orders."""
    def col(*patterns):
        return next((i for i, h in enumerate(headers) if any(re.search(pt, h, re.I) for pt in patterns)), None)

    idx = {"tx": col(r"transaction"), "orders": col(r"order id"), "method": col(r"method"), "amount": col(r"amount"),
           "refunded": col(r"refund"), "created": col(r"created|date"), "status": col(r"status")}
    if idx["orders"] is None:
        return []
    blank = {"lines": [], "classes": [], "actions": [], "badges": [], "images": []}
    payments = []
    for row in rows:
        def cell(name):
            i = idx[name]
            return row[i] if i is not None and i < len(row) else blank
        ids = re.findall(r"\d+", " ".join(cell("orders")["lines"]))
        if not ids:
            continue
        link = next((a["href"] for a in cell("orders")["actions"] if a["href"]), "")
        trx = re.search(r"query=(\d+)", link)
        method_cell, status_cell = cell("method"), cell("status")
        method = " ".join(method_cell["lines"]) or (method_cell["images"][0]["alt"].replace(" icon", "") if method_cell["images"] else "")
        payments.append({
            "trx": trx.group(1) if trx else "", "order_ids": ids, "method": method.strip(),
            "amount": " ".join(cell("amount")["lines"]), "refunded": " ".join(cell("refunded")["lines"]),
            "created": " ".join(cell("created")["lines"]), "reference": " ".join(cell("tx")["lines"]),
            "status": {"text": " ".join(status_cell["lines"]), "tone": _tone(status_cell["classes"])},
        })
    return payments


def _visible_text(html, limit=240):
    """The readable text of a page, for error details."""
    text = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", str(html or ""))
    return " ".join(unescape(_TAG_RE.sub(" ", text)).split())[:limit]


def _trace(response):
    """What came back for a site button's request: status, redirect chain, final address and the page's words (for the local log)."""
    path = lambda r: urlsplit(str(getattr(r, "url", "") or "")).path or "/"
    hops = [f"{r.status_code} {path(r)}" for r in getattr(response, "history", None) or []] + [f"{response.status_code} {path(response)}"]
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", response.text or "")
    return {"http": response.status_code, "url": str(getattr(response, "url", "")), "hops": " → ".join(hops),
            "title": _clean_message(title.group(1))[:80] if title else "", "page": _visible_text(response.text)}


def _public_orders(orders):
    return [{k: v for k, v in order.items() if k != "_raw"} for order in orders or []]


def _cancel_path(args, order_id):
    """`cancel_order("<base64 path>")` from the site's own button -> the path it navigates to."""
    try:
        path = base64.b64decode(args[0] if args else "", validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise LeoFameError("The site's cancel link could not be read.")
    if path != f"/dashboard/cancel/{order_id}":
        raise LeoFameError("The site's cancel link does not match this order.")
    return path


def _refund_path(args, order_id):
    path = _site_path(urljoin(BASE + ORDERS_PATH, args[0] if args else ""))
    if not path or str(order_id) not in path:
        raise LeoFameError("The site's refund link does not match this order.")
    return path


class JsonFile:
    """A small JSON file in DATA_DIR, written atomically."""

    def __init__(self, name, default):
        self.path = DATA_DIR / name
        self._default = default
        self._lock = threading.Lock()

    def read(self):
        with self._lock:
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return json.loads(json.dumps(self._default))

    def write(self, value):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)


class LeoFameClient:
    """HTTP client: sign-in, balance and the free TikTok views form."""

    def __init__(self, session_path, timezone_name=""):
        self.timezone = timezone_name
        self._session_path = Path(session_path)
        self._lock = threading.RLock()
        self._order_lock = threading.RLock()   # the site keeps the cart in the session: one order flow at a time
        self._prepared = None                  # last verified post, ready to be paid
        self._browse = None                    # token + account used to page through the account's posts
        self._known_posts = {}                 # account -> post keys the site has shown us (what may be selected)
        self._http = requests.Session()
        self._http.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        self._load_cookies()

    # -- session persistence -------------------------------------------------

    def _load_cookies(self):
        try:
            cookies = json.loads(self._session_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for name, value in cookies.items():
            self._http.cookies.set(name, value, domain="leofame.com", path="/")

    def _save_cookies(self):
        self._session_path.parent.mkdir(parents=True, exist_ok=True)
        cookies = requests.utils.dict_from_cookiejar(self._http.cookies)
        self._session_path.write_text(json.dumps(cookies), encoding="utf-8")

    def _forget_cookies(self):
        self._http.cookies.clear()
        try:
            self._session_path.unlink()
        except OSError:
            pass

    # -- low level -----------------------------------------------------------

    def _request(self, method, path, **kwargs):
        kwargs.setdefault("timeout", 30)
        try:
            response = self._http.request(method, BASE + path, **kwargs)
        except requests.RequestException as exc:
            raise LeoFameError(f"Could not reach leofame.com ({exc.__class__.__name__}).", network=True) from exc
        if response.status_code in (403, 429, 503) and "cloudflare" in response.text[:4000].lower():
            raise LeoFameError("leofame.com is asking for a browser check (Cloudflare). Try again shortly.", network=True)
        return response

    @staticmethod
    def _extract_token(html):
        match = _TOKEN_RE.search(html) or _TOKEN_VAR_RE.search(html)
        if not match:
            raise LeoFameError("Could not find the page's security token.")
        return match.group(1)

    # -- account -------------------------------------------------------------

    def account(self):
        """Return {'logged_in': bool, 'balance_text': str, 'balance': float}."""
        with self._lock:
            html = self._request("GET", "/").text
        match = _BALANCE_RE.search(html)
        if not match:
            return {"logged_in": False, "balance_text": "", "balance": 0.0}
        text = match.group(1).strip()
        amount = _AMOUNT_RE.search(text)
        value = float(amount.group(0).replace(",", "")) if amount else 0.0
        return {"logged_in": True, "balance_text": text, "balance": value}

    def login(self, email, password):
        with self._lock:
            self._forget_cookies()
            page = self._request("GET", LOGIN_PATH)
            token = self._extract_token(page.text)
            response = self._request(
                "POST", SIGN_IN_PATH,
                data={"email": email, "password": password, "token": token, "remember": "on"},
                headers={"X-Requested-With": "XMLHttpRequest", "Origin": BASE, "Referer": BASE + LOGIN_PATH},
            )
            try:
                data = json.loads(response.text.strip())
            except ValueError as exc:
                raise LeoFameError("Unexpected response from the sign-in endpoint.") from exc
            if data.get("status") != "success":
                raise LeoFameError(_clean_message(data.get("message")) or "Sign-in failed.")
            account = self.account()
            if not account["logged_in"]:
                raise LeoFameError("Sign-in was accepted but the session was not established.")
            self._save_cookies()
            return account

    def logout(self):
        with self._lock:
            try:
                self._request("GET", "/logout")
            except LeoFameError:
                pass
            self._forget_cookies()

    # -- orders --------------------------------------------------------------

    def orders(self, path):
        """Fetch one orders page. Returns None when the session is no longer signed in."""
        with self._lock:
            html = self._request("GET", path).text
        if 'id="result_ajaxSearch"' not in html:
            return None  # redirected to the login page
        page = _OrdersPage()
        page.feed(html)
        page.close()
        rows, notice = page.rows, ""
        if rows and all(len(row) == 1 for row in rows):  # a single spanning cell = "no data" message
            notice, rows = " ".join(" ".join(r[0]["lines"]) for r in rows), []
        counts = {}
        for status, label in _ORDER_TAB_RE.findall(html):
            digits = re.findall(r"\d+", _TAG_RE.sub(" ", label))
            if status in ORDER_STATUSES and digits:
                counts[status] = int(digits[-1])
        balance = _BALANCE_RE.search(html)
        account = {"logged_in": True, "balance_text": "$0.00", "balance": 0.0}
        if balance:
            amount = _AMOUNT_RE.search(balance.group(1))
            account.update(balance_text=balance.group(1).strip(), balance=float(amount.group(0).replace(",", "")) if amount else 0.0)
        token = _TOKEN_VAR_RE.search(html)
        return {
            "columns": page.headers, "rows": rows, "orders": _build_orders(page.headers, rows), "notice": notice,
            "pages": page.pages, "counts": counts, "account": account, "fetched_at": _now_iso(),
            "token": token.group(1) if token else "",
        }

    # -- what the site's own buttons do on an order ---------------------------

    def find_order(self, order_id):
        """The live row of one order (with the buttons the site offers for it right now) and its page."""
        page = self.orders(f"{ORDERS_PATH}/search?" + urlencode({"query": order_id, "search_type": "1"}))
        if page is None:
            raise LeoFameError("Your session expired. Please sign in again.")
        return next((o for o in page["orders"] if o["id"] == str(order_id)), None), page

    @staticmethod
    def _refusal(response, trace, what):
        """The site answered the button's request with an error: say so, with the facts, instead of waiting in vain."""
        facts = f"HTTP {trace['http']} · {trace['url']} · {trace['page']}"
        if response.status_code >= 400:
            raise LeoFameError(f"leofame.com refused the {what} (HTTP {response.status_code}).", details=facts)
        try:
            _site_message(response)
        except LeoFameError as exc:
            raise LeoFameError(str(exc), details=facts)

    def order_action(self, order_id, kind, reason=""):
        """Press one of the site's buttons for an order: cancel, refund request or a site link.

        The button is looked up in the live page and its target is validated, so only what the
        site itself offers for that order can ever be sent.
        """
        order, page = self.find_order(order_id)
        if not order:
            raise LeoFameError(f"Order #{order_id} was not found on your account.")
        raw = next((a for a in order["_raw"]["actions"] if a["kind"] == kind), None)
        if not raw:
            raise LeoFameError("That action is not available for this order any more.")
        headers = {**_NAV_HEADERS, "Referer": BASE + ORDERS_PATH}
        message, trace = "", {}
        if kind == "cancel":
            sent = self._request("GET", _cancel_path(raw["args"], order_id), headers=headers)
            trace = _trace(sent)
            self._refusal(sent, trace, "cancel")
        elif kind == "refund":
            reason = " ".join(str(reason or "").split())
            if not reason:
                raise ValueError("Please enter a reason.")
            response = self._request(
                "POST", _refund_path(raw["args"], order_id), data={"reason": reason, "token": page["token"]},
                headers={**self._XHR, **headers})
            message = _site_message(response)
        elif kind == "link":
            path = _site_path(raw["href"])
            if not path:
                raise LeoFameError("The site's link could not be used.")
            sent = self._request("GET", path, headers=headers)
            trace = _trace(sent)
            self._refusal(sent, trace, "request")
        after, latest = self.find_order(order_id)
        return {"before": order, "after": after, "message": message, "account": latest["account"], "trace": trace}

    def payments(self):
        """Every payment of the account (billing page), newest first. None when the session is gone."""
        with self._lock:
            html = self._request("GET", "/dashboard/billing").text
        if 'id="balance-txt"' not in html:
            return None
        page = _OrdersPage(anywhere=True)
        page.feed(html)
        page.close()
        return _build_payments(page.headers, page.rows)

    def payment_details(self, order_id):
        """The payment (billing) records of an order, as the site's billing page shows them."""
        with self._lock:
            html = self._request("GET", "/dashboard/billing?" + urlencode({"query": order_id, "search_type": "3"})).text
        if 'id="balance-txt"' not in html:
            return None
        page = _OrdersPage(anywhere=True)
        page.feed(html)
        page.close()
        records = []
        for row in page.rows:
            fields, tone = {}, ""
            for header, cell in zip(page.headers, row):
                text = " ".join(cell["lines"]) or (cell["images"][0]["alt"].replace(" icon", "") if cell["images"] else "")
                fields[header] = text
                if re.search("status", header, re.I):
                    tone = _tone(cell["classes"]) or _tone([c for b in cell["badges"] for c in b["classes"]])
            if fields:
                records.append({"fields": fields, "tone": tone})
        return records

    # -- buying views: catalog, verify a post, checkout ----------------------

    _XHR = {"X-Requested-With": "XMLHttpRequest", "Origin": BASE}

    def _select(self, item_id, custom_quantity=None):
        """Put a package in the site's cart and return the order-details page."""
        path = f"/order/select?item_id={item_id}&api=true&subscription_enabled=false"
        if custom_quantity:
            path += f"&custom_quantity={int(custom_quantity)}"
        self._prepared = None  # the cart changed
        self._request("GET", path)
        page = self._request("GET", "/order/details").text
        if 'id="checkout_details_form"' not in page:
            raise LeoFameError("The order page is not available right now. Please try again.")
        return page

    @staticmethod
    def _input_value(page, tag_re):
        tag = tag_re.search(page)
        value = re.search(r'value="([^"]*)"', tag.group(0)) if tag else None
        return unescape(value.group(1)) if value else ""

    @staticmethod
    def _speeds(page, item_id):
        match = _DELIVERY_RE.search(page)
        try:
            return _delivery_options(json.loads(match.group(1)).get(str(item_id))) if match else []
        except ValueError:
            return []

    def catalog(self):
        """Packages, prices and delivery speeds as the site offers them."""
        with self._order_lock:
            buy = self._request("GET", BUY_PATH).text
            details = self._select(CUSTOM_ITEM_ID)
            saves = {q: (best == "best", save.strip()) for q, best, save in _SAVE_RE.findall(buy)}
            packages, delivery = [], {}
            for quantity, price, item_id in _PANE_RE.findall(buy):
                best, save = saves.get(quantity, (False, ""))
                packages.append({"id": item_id, "quantity": int(quantity), "price": float(price),
                                 "save": save if save.lower().startswith("save") else "", "best": best})
            for package in packages:
                delivery[package["id"]] = self._speeds(details, package["id"])
            limits = _CUSTOM_RE.search(buy)
            prices = _PRICES_RE.search(buy)
            if not packages:
                raise LeoFameError("Could not read the package list from leofame.com.")
            return {
                "packages": packages,
                "delivery": delivery,
                "custom": {
                    "item_id": CUSTOM_ITEM_ID,
                    "min": int(limits.group(1)) if limits else 500,
                    "max": int(limits.group(2)) if limits else 100000,
                    "prices": {int(k): float(v) for k, v in json.loads(prices.group(1)).items()} if prices else {},
                },
                "card_minimum": CARD_MINIMUM,
            }

    def quote(self, item_id, custom_quantity):
        """Exact price and delivery speeds for a custom quantity."""
        with self._order_lock:
            page = self._select(item_id, custom_quantity)
        match = _ITEMS_RE.search(page)
        try:
            item = next(i for i in json.loads(match.group(1)) if i.get("selected"))
        except (AttributeError, StopIteration, ValueError):
            raise LeoFameError("Could not price that quantity.")
        return {"quantity": int(custom_quantity), "price": _price(item.get("price")), "delivery": self._speeds(page, item_id)}

    def prepare_order(self, item_id, link, email, delivery, custom_quantity=None):
        """Verify a TikTok post with the site and return a preview (nothing is bought yet)."""
        username_param = parse_tiktok_link(link)
        if not _EMAIL_RE.match(str(email or "")) or len(email) > 64:
            raise ValueError("Enter a valid email address.")
        with self._order_lock:
            page = self._select(item_id, custom_quantity)
            options = self._speeds(page, item_id)
            if str(delivery) not in {o["value"] for o in options}:
                delivery = next((o["value"] for o in options if o["recommended"]), options[0]["value"] if options else "0")
            response = self._request(
                "POST", "/order/check",
                data={"username": username_param, "type": "post", "email": email, "delivery_hours": delivery,
                      "item_id": item_id, "optmail": "off", "raw_link": link, "token": self._extract_token(page)},
                headers={**self._XHR, "Referer": BASE + "/order/details"},
            )
            try:
                data = json.loads(response.text.strip())
            except ValueError:
                raise LeoFameError("Unexpected response while checking the post.")
            if data.get("inprogress_order_error"):
                raise LeoFameError(_clean_message(data["inprogress_order_error"]) + " Wait until it finishes, then try again.")
            if data.get("error"):
                if data.get("info") == "not_found" or data.get("d") == "not_found":
                    raise LeoFameError("That TikTok post could not be found. Check the link and make sure the account is public.")
                raise LeoFameError(_clean_message(data["error"]))
            if not data.get("redirect"):
                raise LeoFameError("The site did not accept this link.")

            chooser = self._request("GET", "/order/choose-posts").text
            token = self._extract_token(chooser)
            username = self._input_value(chooser, _USERNAME_FIELD_RE)
            image = _ACCOUNT_IMAGE_RE.search(chooser)
            more = self._request("POST", "/order/more-posts", data={"account": username, "cursor": "", "token": token},
                                 headers={**self._XHR, "Referer": BASE + "/order/choose-posts"})
            try:
                listing = json.loads(more.text.strip())
            except ValueError:
                raise LeoFameError("Could not load the post from TikTok.")
            if listing.get("error"):
                raise LeoFameError(_clean_message(listing["error"]))
            post = next((p for p in listing.get("items") or [] if p.get("selected")), None)
            if not post:
                raise LeoFameError("The site could not match that link to a post on the account.")

            quantity = int(custom_quantity) if custom_quantity else None
            price_match = re.search(r'class="price">\s*([^<]+)<', chooser)
            qty_match = re.search(r"<span>([\d,]+)</span>\s*Views", chooser)
            min_match = re.search(r"var\s+minimum_quantity\s*=\s*(\d+)", chooser)
            picked = _post_info(post)
            self._browse = {"token": token, "username": username}
            self._remember_posts(username, [picked])
            posts = self._unique_posts(username, listing.get("items"))
            self._prepared = {
                "key": (str(item_id), quantity, str(delivery), link, email),
                "token": token, "username": username, "account_posts": picked["key"],
                "quantity": int(qty_match.group(1).replace(",", "")) if qty_match else quantity,
                "min_per_post": int(min_match.group(1)) if min_match else 100,
                "at": time.time(),
            }
            return {
                "delivery": str(delivery),
                "package": {"quantity": self._prepared["quantity"], "price": _price(price_match.group(1)) if price_match else 0.0},
                "account": {"username": username, "image": unescape(image.group(1)) if image else ""},
                "post": {**picked, "link": picked["link"] or link},
                "posts": posts, "cursor": listing.get("cursor") or None,
                "selected_key": picked["key"], "min_per_post": self._prepared["min_per_post"],
            }

    # -- the account's posts (the site's "Select posts" step) ------------------

    def _remember_posts(self, username, posts):
        self._known_posts.setdefault(username.lower(), set()).update(p["key"] for p in posts)

    def _unique_posts(self, username, items):
        seen, posts = set(), []
        for item in items or []:
            info = _post_info(item)
            if info["key"] and info["key"] not in seen and not info["private"]:
                seen.add(info["key"])
                posts.append(info)
        self._remember_posts(username, posts)
        return posts

    def more_posts(self, cursor, account=""):
        """Next page of a verified account's posts. `cursor` comes from the previous page."""
        browse = self._browse
        account = str(account or (browse or {}).get("username") or "")
        if not browse or not cursor or not account:
            raise ValueError("There are no more posts to load.")
        if account.lower() not in self._known_posts:
            raise ValueError("Verify a post from that account first.")
        with self._order_lock:
            response = self._request(
                "POST", "/order/more-posts", headers={**self._XHR, "Referer": BASE + "/order/choose-posts"},
                data={"account": account, "cursor": str(cursor), "token": browse["token"]})
            try:
                listing = json.loads(response.text.strip())
            except ValueError:
                raise LeoFameError("Could not load more posts from TikTok.")
            if listing.get("redirect"):
                raise LeoFameError("Your session expired. Please verify your post again.")
            if listing.get("error") or listing.get("error_with_cursor"):
                raise LeoFameError(_clean_message(listing.get("error")) or "TikTok did not return more posts. Try again.")
            return {"posts": self._unique_posts(account, listing.get("items")), "cursor": listing.get("cursor") or None}

    def _selected_posts(self, prepared, posts):
        """The post keys to buy views for: the user's choice (validated), or just the pasted post."""
        if not posts:
            return [prepared["account_posts"]]
        known = self._known_posts.get(prepared["username"].lower(), set())
        keys = []
        for key in posts:
            key = str(key)
            if key not in known:
                raise ValueError("Choose posts from your account's list.")
            if key not in keys:
                keys.append(key)
        limit = max(1, (prepared["quantity"] or 0) // prepared["min_per_post"])
        if len(keys) > limit:
            raise ValueError(f"{prepared['quantity']:,} views can cover at most {limit} posts (at least {prepared['min_per_post']} views each).")
        return keys

    def start_payment(self, item_id, link, email, delivery, custom_quantity=None, posts=None):
        """Create the order and return the Mastercard hosted-checkout URL. Nothing is charged here."""
        key = (str(item_id), int(custom_quantity) if custom_quantity else None, str(delivery), link, email)
        with self._order_lock:
            prepared = self._prepared
            if not prepared or prepared["key"] != key or time.time() - prepared["at"] > PREPARED_TTL:
                self.prepare_order(item_id, link, email, delivery, custom_quantity)
                prepared = self._prepared
            chosen = self._selected_posts(prepared, posts)
            step = self._request(
                "POST", "/order/choose-posts", allow_redirects=False,
                data={"token": prepared["token"], "account_posts": ",".join(chosen), "username": prepared["username"]},
                headers={"Origin": BASE, "Referer": BASE + "/order/choose-posts"},
            )
            if step.status_code not in (301, 302, 303, 307):
                raise LeoFameError("The site did not accept the selected post.")
            page = self._request("GET", "/order/checkout").text
            if 'id="payment-form"' not in page:
                raise LeoFameError("Checkout is not available right now. Please try again.")

            # Safety net: what the site will charge for must be exactly what the user chose.
            shown = _CHECKOUT_ITEM_RE.search(page)
            owner = _CHECKOUT_USER_RE.search(page)
            if shown and prepared["quantity"] and int(shown.group(1).replace(",", "")) != prepared["quantity"]:
                self._prepared = None
                raise LeoFameError("The cart changed unexpectedly. Please verify your post again.")
            if owner and prepared["username"] and owner.group(1).strip().lstrip("@").lower() != prepared["username"].lower():
                self._prepared = None
                raise LeoFameError("The cart changed unexpectedly. Please verify your post again.")
            split = _CHECKOUT_SPLIT_RE.search(page)
            if split and int(split.group(1)) != len(chosen):
                self._prepared = None
                raise LeoFameError("The site did not keep your post selection. Please verify your post again.")

            total = _TOTAL_RE.search(page)
            total = float(total.group(1)) if total else None
            if total is not None and total <= 0:
                raise LeoFameError("Your Leofame balance already covers this order, so no card payment is needed. Finish it on leofame.com.")
            form = dict(_HIDDEN_RE.findall(page[page.find('id="payment-form"'):]))
            gateways = _GATEWAY_RE.findall(page)
            gateway = next((gid for gid, title in gateways if "card" in unescape(_TAG_RE.sub("", title)).lower()), None)
            if not gateway or not form.get("checkout_id"):
                raise LeoFameError("Card payment is not available for this order right now.")
            form.update(gateway_id=gateway, agree="on")
            form.setdefault("browser_support", "1")

            response = self._request("POST", "/order/checkout", data=form, allow_redirects=False,
                                     headers={"Origin": BASE, "Referer": BASE + "/order/checkout"})
            url = None
            for _ in range(4):
                url = find_payment_url(response.headers.get("Location", "")) or find_payment_url(response.text)
                location = response.headers.get("Location")
                if url or not location or response.status_code not in (301, 302, 303, 307):
                    break
                if location.startswith("/") or urlsplit(location).hostname in ("leofame.com", "www.leofame.com"):
                    response = self._request("GET", urlsplit(location).path + (f"?{urlsplit(location).query}" if urlsplit(location).query else ""), allow_redirects=False)
                else:
                    break
            if not url:
                try:
                    problem = _clean_message(json.loads(response.text.strip()).get("error", ""))
                except (ValueError, AttributeError):
                    problem = ""
                raise LeoFameError(problem or "The site did not return a payment page. Please try again.")
            self._prepared = None
            charge = max(total, CARD_MINIMUM) if total is not None else CARD_MINIMUM
            trx = find_transaction_id(response.headers.get("Location", "")) or find_transaction_id(response.text)
            return {"payment_url": url, "total": total, "charge": charge, "posts": len(chosen), "trx": trx,
                    "credit": round(charge - total, 2) if total is not None else 0.0}

    # -- free TikTok views ---------------------------------------------------

    def prepare_free_views(self):
        """Load the free-views page and return its security token and allowed quantities."""
        with self._lock:
            html = self._request("GET", FREE_VIEWS_PATH).text
        token = self._extract_token(html)
        select = _QUANTITY_SELECT_RE.search(html)
        quantities = [int(q) for q in _OPTION_RE.findall(select.group(1))] if select else []
        return {"token": token, "quantities": quantities or DEFAULT_QUANTITIES}

    def submit_free_views(self, link, quantity, token):
        """POST the free form exactly like the page script. Returns {'ok': bool, 'message': str}."""
        payload = [
            ("token", token),
            ("timezone_offset", self.timezone or _local_timezone()),
            # The page script replaces the default "1234" with "abcd" when the form is submitted.
            ("timezone_offset_2", "abcd"),
            ("free_link", link),
            ("quantity", str(quantity)),
        ]
        with self._lock:
            response = self._request(
                "POST", FREE_VIEWS_PATH + "?api=1", data=payload,
                headers={"Origin": BASE, "Referer": BASE + FREE_VIEWS_PATH},
            )
            self._save_cookies()
        try:
            data = json.loads(response.text.strip())
        except ValueError:
            return {"ok": False, "message": "The site returned an unexpected response (no JSON)."}
        if data.get("success"):
            return {"ok": True, "message": _clean_message(data["success"])}
        if data.get("error"):
            return {"ok": False, "message": _clean_message(data["error"])}
        return {"ok": False, "message": "The site returned an unexpected response."}


class Automation:
    """Everything the UI needs: automatic sign-in, balance, free-views jobs and history."""

    def __init__(self):
        self._config = JsonFile("config.json", {"email": "", "password": "", "timezone": ""})
        self._history = JsonFile("history.json", [])
        self.client = LeoFameClient(DATA_DIR / "session.json", self._config.read().get("timezone", ""))
        self._lock = threading.RLock()
        self.stage = "connecting"      # connecting | signing_in | ready | needs_login | offline
        self.message = "Connecting to leofame.com"
        self.error = ""
        self.account = {"logged_in": False, "balance_text": "", "balance": 0.0}
        self._jobs = {}
        self.active_job = None
        self._catalog = None
        self._pay_lock = threading.Lock()
        self._payments_cache = (0.0, [])

    # -- automatic sign-in ---------------------------------------------------

    def _set(self, stage, message="", error=""):
        with self._lock:
            self.stage, self.message, self.error = stage, message, error

    def bootstrap(self):
        """Restore the saved session, or sign in with the saved account."""
        self._set("connecting", "Connecting to leofame.com")
        try:
            account = self.client.account()
            if not account["logged_in"]:
                cfg = self._config.read()
                if not (cfg.get("email") and cfg.get("password")):
                    return self._set("needs_login", "Sign in to continue")
                self._set("signing_in", "Signing in automatically")
                account = self.client.login(cfg["email"], cfg["password"])
        except LeoFameError as exc:
            return self._set("offline" if exc.network else "needs_login", "", str(exc))
        with self._lock:
            self.account = account
        self._set("ready", "Ready")

    def start_bootstrap(self):
        threading.Thread(target=self.bootstrap, daemon=True).start()

    def sign_in(self, email, password):
        email = str(email or "").strip()
        if not email or not password:
            raise ValueError("Enter your email and password.")
        account = self.client.login(email, password)
        cfg = self._config.read()
        cfg.update(email=email, password=password)
        self._config.write(cfg)
        with self._lock:
            self.account = account
        self._set("ready", "Ready")

    def sign_out(self):
        self.client.logout()
        cfg = self._config.read()
        cfg.update(email="", password="")
        self._config.write(cfg)
        with self._lock:
            self.account = {"logged_in": False, "balance_text": "", "balance": 0.0}
        self._set("needs_login", "Signed out")

    def refresh_account(self):
        account = self.client.account()
        if not account["logged_in"]:
            return self.bootstrap()
        with self._lock:
            self.account = account

    def set_timezone(self, name):
        cfg = self._config.read()
        cfg["timezone"] = str(name or "").strip()
        self._config.write(cfg)
        self.client.timezone = cfg["timezone"]

    def state(self):
        cfg = self._config.read()
        with self._lock:
            return {
                "stage": self.stage, "message": self.message, "error": self.error,
                "email": cfg.get("email", ""),
                "has_credentials": bool(cfg.get("email") and cfg.get("password")),
                "timezone": cfg.get("timezone", ""),
                "account": self.account,
                "active_job": self.active_job,
                "wait_seconds": FORM_WAIT_SECONDS,
            }

    # -- orders --------------------------------------------------------------

    @staticmethod
    def _orders_path(status, query, search_type, url):
        if url:
            parts = urlsplit(url)
            if parts.netloc not in ("", "leofame.com", "www.leofame.com") or not parts.path.startswith(ORDERS_PATH):
                raise ValueError("Invalid page.")
            return parts.path + (f"?{parts.query}" if parts.query else "")
        query = str(query or "").strip()
        if query:
            if str(search_type) not in ORDER_SEARCH_TYPES:
                raise ValueError("Unknown search type.")
            if str(search_type) == "3":
                query = _link_search_term(query)
            return f"{ORDERS_PATH}/search?" + urlencode({"query": query, "search_type": search_type})
        if status not in ORDER_STATUSES:
            raise ValueError("Unknown order status.")
        return f"{ORDERS_PATH}/{status}"

    def _signed_in(self, call):
        """Run `call()`; if the session has expired, sign in again with the saved account and retry once."""
        try:
            return call()
        except LeoFameError as exc:
            if "session expired" not in str(exc).lower():
                raise
        self.bootstrap()
        if self.stage != "ready":
            raise LeoFameError(self.error or "Your session expired. Please sign in again.")
        return call()

    def _payments(self):
        """Billing records (cached for a few seconds). An empty list if the billing page cannot be read."""
        with self._lock:
            stamp, cached = self._payments_cache
        if cached and time.time() - stamp < 5:
            return cached
        try:
            fresh = self.client.payments()
        except LeoFameError:
            return cached
        if fresh is None:
            return cached
        with self._lock:
            self._payments_cache = (time.time(), fresh)
        return fresh

    def _log(self, event, **data):
        """A small local trail of what the app did for an order (no cookies, no tokens)."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            path = DATA_DIR / LOG_FILE
            if path.exists() and path.stat().st_size > 200_000:
                path.write_text("", encoding="utf-8")
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"time": _now_iso(), "event": event, **data}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def orders(self, status="all", query="", search_type="1", url="", with_payments=False):
        """The account's order history (one page), filtered by status, search or a pagination link."""
        path = self._orders_path(status, query, search_type, url)
        result = self.client.orders(path)
        if result is None:  # session expired: sign in again with the saved account, then retry once
            self.bootstrap()
            if self.stage != "ready":
                raise LeoFameError(self.error or "Your session expired. Please sign in again.")
            result = self.client.orders(path)
            if result is None:
                raise LeoFameError("Could not load your orders.")
        with self._lock:
            self.account = result["account"]
        public = _public_orders(result["orders"])
        if with_payments:
            payments = self._payments()
            for order in public:
                found = next((p for p in payments if order["id"] in p["order_ids"]), None)
                order["payment"] = {**found, "shared": [i for i in found["order_ids"] if i != order["id"]]} if found else None
        return {
            **{k: v for k, v in result.items() if k not in ("token", "rows", "orders")},
            "orders": public,
            # generic fallback for a table layout we do not recognise: plain text only
            "rows": [[{"lines": c["lines"], "classes": c["classes"], "progress": c["progress"]} for c in row] for row in result["rows"]],
        }

    @staticmethod
    def _order_id(order_id):
        order_id = str(order_id or "").strip()
        if not re.fullmatch(r"\d{1,12}", order_id):
            raise ValueError("Invalid order.")
        return order_id

    @staticmethod
    def _still_open(order):
        """True while leofame.com still offers to cancel this order (i.e. it has not been cancelled yet)."""
        return order is not None and "cancel" not in order["status"]["text"].lower() and any(a["kind"] == "cancel" for a in order["actions"])

    def _wait_for_cancel(self, ids, wait=None):
        """leofame.com may take a few seconds to finish a cancellation: look again until every order shows it."""
        deadline, pending, latest = time.time() + (CANCEL_WAIT if wait is None else wait), set(ids), {}
        while pending and time.time() < deadline:
            time.sleep(1.5)
            page = self.client.orders(f"{ORDERS_PATH}/all")
            if page is None:
                break
            listed = {o["id"]: o for o in page["orders"]}
            for oid in list(pending):
                order = listed.get(oid) or self.client.find_order(oid)[0]   # older than the first page: ask directly
                latest[oid] = order
                if not self._still_open(order):
                    pending.discard(oid)
        return latest, pending

    def order_action(self, order_id, kind, reason=""):
        """Cancel an order / request a refund / follow a site link, then return the order as it is now.

        A cancellation that leofame.com has accepted but not finished yet comes back with pending=True.
        """
        self._require_ready()
        order_id = self._order_id(order_id)
        if kind not in ("cancel", "refund", "link"):
            raise ValueError("Unknown action.")
        result = self._signed_in(lambda: self.client.order_action(order_id, kind, reason))
        after, trace, pending = result["after"], result.get("trace") or {}, False
        if kind == "cancel":
            if self._still_open(after):
                latest, waiting = self._wait_for_cancel([order_id])
                after, pending = latest.get(order_id, after), bool(waiting)
            self._log("cancel", order=order_id, before=result["before"]["status"]["text"], after=(after or {}).get("status", {}).get("text"), pending=pending, **trace)
            if pending:
                message = f"Cancel request for order #{order_id} was sent. leofame.com is still processing it."
            else:
                message = f"Order #{order_id} was cancelled."
        elif kind == "refund":
            message = result["message"] or f"Refund request for order #{order_id} was sent."
            self._log("refund", order=order_id, message=message)
        else:
            message = result["message"] or "Done."
            self._log("link", order=order_id, **trace)
        with self._lock:
            self.account = result["account"]
        return {"ok": True, "pending": pending, "message": message, "account": result["account"],
                "order": _public_orders([after])[0] if after else None}

    def cancel_orders(self, order_ids):
        """Cancel several orders at once (e.g. all unpaid orders of a payment)."""
        self._require_ready()
        ids = list(dict.fromkeys(self._order_id(i) for i in (order_ids or [])))
        if not ids:
            raise ValueError("Choose the orders to cancel.")
        results, sent = {}, []
        for oid in ids:
            try:
                sent_result = self._signed_in(lambda oid=oid: self.client.order_action(oid, "cancel", ""))
                sent.append(oid)
                results[oid] = {"id": oid, "before": sent_result["before"], "after": sent_result["after"], "trace": sent_result.get("trace") or {}}
            except (LeoFameError, ValueError) as exc:
                results[oid] = {"id": oid, "error": str(exc), "details": getattr(exc, "details", "")}
        open_now = [oid for oid in sent if self._still_open(results[oid]["after"])]
        latest, waiting = self._wait_for_cancel(open_now) if open_now else ({}, set())
        out = []
        for oid in ids:
            r = results[oid]
            if "error" in r:
                out.append({"id": oid, "ok": False, "error": r["error"], "details": r["details"]})
                continue
            after = latest.get(oid, r["after"])
            pending = oid in waiting
            self._log("cancel", order=oid, before=r["before"]["status"]["text"], after=(after or {}).get("status", {}).get("text"), pending=pending, bulk=True, **r["trace"])
            out.append({"id": oid, "ok": True, "pending": pending, "order": _public_orders([after])[0] if after else None})
        account = self.orders("all")["account"]
        return {"results": out, "account": account}

    def payment_details(self, order_id):
        """Payment (billing) records of one order."""
        self._require_ready()
        order_id = self._order_id(order_id)
        records = self._signed_in(lambda: self.client.payment_details(order_id))
        if records is None:
            raise LeoFameError("Your session expired. Please sign in again.")
        return {"order_id": order_id, "records": records}

    # -- buying views --------------------------------------------------------

    def _require_ready(self):
        if self.stage != "ready":
            raise ValueError("Sign in first.")

    def catalog(self):
        """Packages, prices and delivery speeds (cached for a few minutes)."""
        with self._lock:
            if self._catalog and time.time() - self._catalog[0] < CATALOG_TTL:
                return self._catalog[1]
        self._require_ready()
        data = self.client.catalog()
        with self._lock:
            self._catalog = (time.time(), data)
        return data

    def _order_args(self, item_id, custom_quantity, delivery, email):
        catalog = self.catalog()
        item_id = str(item_id or "")
        if item_id not in {p["id"] for p in catalog["packages"]}:
            raise ValueError("Choose a package.")
        quantity = None
        if custom_quantity not in (None, ""):
            limits = catalog["custom"]
            try:
                quantity = int(custom_quantity)
            except (TypeError, ValueError):
                raise ValueError("Enter a valid quantity.")
            if item_id != limits["item_id"] or not limits["min"] <= quantity <= limits["max"]:
                raise ValueError(f"Custom quantity must be between {limits['min']:,} and {limits['max']:,}.")
        email = str(email or "").strip() or self._config.read().get("email", "")
        return item_id, quantity, str(delivery or ""), email

    def quote(self, custom_quantity):
        """Exact price and delivery speeds for a custom quantity."""
        item_id, quantity, _, _ = self._order_args(CUSTOM_ITEM_ID, custom_quantity, "", "")
        if quantity is None:
            raise ValueError("Enter a quantity.")
        return self.client.quote(item_id, quantity)

    def verify_order(self, item_id, link, email, delivery, custom_quantity=None):
        """Check the post with the site and return a preview. Nothing is bought."""
        item_id, quantity, delivery, email = self._order_args(item_id, custom_quantity, delivery, email)
        return self.client.prepare_order(item_id, str(link or "").strip(), email, delivery, quantity)

    def more_posts(self, cursor, account=""):
        """Next page of a verified account's posts (for the "Select posts" step)."""
        self._require_ready()
        return self.client.more_posts(cursor, account)

    def pay_order(self, item_id, link, email, delivery, custom_quantity=None, agree=False, posts=None):
        """Create the order and return the secure card-payment URL (the user pays on Mastercard's page)."""
        if agree is not True:
            raise ValueError("Please accept the Terms and Refund Policy first.")
        if posts is not None and not isinstance(posts, list):
            raise ValueError("Choose posts from your account's list.")
        item_id, quantity, delivery, email = self._order_args(item_id, custom_quantity, delivery, email)
        with self._pay_lock:  # with several orders open, two payments must not interleave (each finds "its" new orders)
            baseline = [o["id"] for o in self.orders("all")["orders"]]
            result = self.client.start_payment(item_id, str(link or "").strip(), email, delivery, quantity, posts)
            result["baseline"] = baseline
            # The site creates the order(s) as soon as payment starts (one per selected post, and each is
            # cancelled if the payment fails), so remember which orders belong to this payment.
            ids = []
            for attempt in range(4):
                ids = [o["id"] for o in self._new_orders(baseline)]
                if ids:
                    time.sleep(1)  # siblings of a multi-post order appear a moment apart
                    ids = [o["id"] for o in self._new_orders(baseline)] or ids
                    break
                time.sleep(1)
            result["order_ids"] = ids
            result["order_id"] = ids[0] if ids else None
            self._log("pay", orders=ids, trx=result.get("trx", ""), total=result.get("total"), charge=result.get("charge"),
                      posts=result.get("posts"), url=_safe_url(result["payment_url"]))
            return result

    def _new_orders(self, baseline):
        known = {str(b) for b in (baseline or [])}
        return [o for o in self.orders("all")["orders"] if o["id"] not in known]

    def payment_check(self, baseline, order_ids=None, order_id=None, trx=""):
        """Live state of the order(s) of one payment, with the payment record leofame.com holds for them.

        The order tells us what leofame.com will deliver; the payment record tells us what happened to the card
        (still waiting for the funds, charged, or refused), which is what the person actually wants to know.
        """
        ids = {str(i) for i in (order_ids or [])} | ({str(order_id)} if order_id else set())
        result = self.orders("all", with_payments=True)
        if ids:
            mine = [o for o in result["orders"] if o["id"] in ids]
        else:
            known = {str(b) for b in (baseline or [])}
            mine = [o for o in result["orders"] if o["id"] not in known]
        payment = next((o["payment"] for o in mine if o.get("payment")), None)
        if payment is None and trx:                       # paid, but the order has not appeared yet
            payment = next((p for p in self._payments() if p["trx"] == str(trx)), None)
        return {"orders": mine, "payment": payment, "account": result["account"]}

    # -- free views jobs -----------------------------------------------------

    def start_job(self, link, quantity):
        link = str(link or "").strip()
        if not TIKTOK_LINK_RE.match(link):
            raise ValueError("Enter a valid TikTok post link.")
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            raise ValueError("Choose a quantity.")
        with self._lock:
            if self.stage != "ready":
                raise ValueError("Sign in first.")
            if self.active_job:
                raise ValueError("Another request is still running.")
            job = {
                "id": uuid.uuid4().hex[:10], "link": link, "quantity": quantity,
                "status": "preparing", "progress": 0, "message": "Preparing request",
                "created_at": _now_iso(), "finished_at": None,
            }
            self._jobs[job["id"]] = job
            self.active_job = job["id"]
        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
        return dict(job)

    def job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def _update(self, job, **fields):
        with self._lock:
            job.update(fields)

    def _run_job(self, job):
        try:
            form = self.client.prepare_free_views()
            if job["quantity"] not in form["quantities"]:
                raise LeoFameError(f"{job['quantity']} is not an available quantity.")
            self._update(job, status="waiting", message="Waiting for the site's processing timer")
            for elapsed in range(FORM_WAIT_SECONDS):
                self._update(job, progress=int(elapsed * 100 / FORM_WAIT_SECONDS))
                time.sleep(1)
            self._update(job, status="submitting", progress=100, message="Submitting request")
            result = self.client.submit_free_views(job["link"], job["quantity"], form["token"])
            self._update(job, status="success" if result["ok"] else "error", message=result["message"])
        except LeoFameError as exc:
            self._update(job, status="error", message=str(exc))
        except Exception as exc:  # keep the app alive whatever happens in a worker
            self._update(job, status="error", message=f"Unexpected error: {exc}")
        finally:
            self._update(job, finished_at=_now_iso())
            entries = self._history.read()
            entries.insert(0, dict(job))
            self._history.write(entries[:HISTORY_LIMIT])
            with self._lock:
                self.active_job = None

    def history(self):
        return self._history.read()

    def clear_history(self):
        self._history.write([])
