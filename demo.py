"""Viewdesk demo - the real UI (ui.py) running on built-in sample data.

No account, no network, nothing is bought: every order, price and payment below is made up.

    python demo.py               # opens the app window
    python demo.py --no-window   # only serves it; open the printed address in any browser
    python demo.py --signed-out  # start on the sign-in screen (any e-mail / password works)
"""
import sys
from datetime import datetime, timedelta

sys.dont_write_bytecode = True  # keep the folder free of __pycache__

import ui

POST = "https://www.tiktok.com/@demo_creator/video/{}"
DELIVERY = [
    {"value": "0", "label": "Instant", "hint": "", "recommended": False},
    {"value": "2", "label": "2 hours", "hint": "Recommended", "recommended": True},
    {"value": "12", "label": "12 hours", "hint": "", "recommended": False},
]


def _ago(hours):
    return (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _order(oid, quantity, remains, price, status, tone, hours, trx, part="", actions=(), notes=(), paid="Paid", refunded="0"):
    done = quantity - remains
    return {
        "id": str(oid), "no": str(oid)[-2:], "service": f"{quantity:,} tiktok views{part}", "item_id": "132",
        "quantity": quantity, "link": POST.format(7100000000000000000 + int(oid)),
        "facts": [
            {"label": "Link", "value": POST.format(7100000000000000000 + int(oid)), "url": POST.format(7100000000000000000 + int(oid))},
            {"label": "Quantity", "value": f"{quantity:,}"},
            {"label": "Remains", "value": str(remains)},
            {"label": "Transaction", "value": f"#{trx}", "payment": True},
        ],
        "progress": round(done / quantity * 100), "price": f"${price:.2f}",
        "status": {"text": status, "tone": tone}, "created": _ago(hours),
        "notes": [{"text": n, "tone": t} for n, t in notes],
        "actions": [{"kind": k, "label": label} for k, label in actions],
        "payment": {
            "trx": str(trx), "reference": f"DEMO-{trx}", "created": _ago(hours), "method": "Mastercard",
            "amount": f"${price:.2f}", "status": {"text": paid, "tone": "ok" if paid == "Paid" else "warn"},
            "refunded": refunded, "order_ids": [str(oid)], "shared": [],
        },
    }


class DemoAutomation:
    """Just enough of app.Automation for ui.py to run on sample data."""

    active_job = None

    def __init__(self, signed_in=True):
        self.stage = "ready" if signed_in else "needs_login"
        self.balance = 12.50
        self._orders = [
            _order(4821903, 1000, 400, 2.49, "Processing", "info", 2, 7710231),
            _order(4821877, 5000, 3250, 9.99, "Processing", "info", 5, 7710190, part=" (1 of 3)"),
            _order(4821850, 500, 500, 1.29, "Pending", "warn", 1, 7710177, paid="Awaiting payment",
                   actions=[("cancel", "Cancel Order")], notes=[("Waiting for the card payment to be confirmed", "warn")]),
            _order(4820512, 2500, 0, 5.99, "Completed", "ok", 30, 7709004),
            _order(4819940, 10000, 0, 14.99, "Completed", "ok", 74, 7708211),
            _order(4818003, 1000, 1000, 2.49, "Canceled", "mute", 120, 7706552, paid="Refunded", refunded="2.49",
                   notes=[("Cancelled by you - the amount went back to your card", "mute")]),
        ]

    # -- state -----------------------------------------------------------------
    def state(self):
        return {
            "stage": self.stage, "message": "Demo mode - sample data" if self.stage == "ready" else "Sign in to continue",
            "error": "", "email": "demo@example.com", "has_credentials": self.stage == "ready", "timezone": "",
            "account": {"logged_in": self.stage == "ready", "balance_text": f"${self.balance:.2f}", "balance": self.balance},
            "active_job": None, "wait_seconds": 50,
        }

    def start_bootstrap(self):
        pass

    def refresh_account(self):
        pass

    def sign_in(self, email, password):
        if not str(email or "").strip() or not password:
            raise ValueError("Enter your email and password.")
        self.stage = "ready"

    def _log(self, event, **data):
        pass

    # -- orders ----------------------------------------------------------------
    def orders(self, status="all", query="", search_type="1", url="", with_payments=False):
        rows = [o for o in self._orders if status in ("", "all") or o["status"]["text"].lower() == status]
        if query:
            rows = [o for o in rows if str(query).lower() in (o["id"] + o["link"]).lower()]
        counts = {"all": len(self._orders)}
        for key in ("pending", "processing", "completed", "canceled"):
            counts[key] = sum(1 for o in self._orders if o["status"]["text"].lower() == key)
        out = [{k: v for k, v in o.items() if with_payments or k != "payment"} for o in rows]
        return {"columns": [], "rows": [], "orders": out, "notice": "", "pages": [], "counts": counts,
                "account": self.state()["account"], "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds")}

    def payment_details(self, order_id):
        order = next((o for o in self._orders if str(o["id"]) == str(order_id)), None)
        return {"payment": order["payment"] if order else None}

    def cancel_orders(self, order_ids):
        for o in self._orders:
            if str(o["id"]) in {str(i) for i in order_ids or []} and o["status"]["text"] == "Pending":
                o["status"], o["actions"] = {"text": "Canceled", "tone": "mute"}, []
        return {"ok": True, "message": "Cancelled (demo)"}

    def order_action(self, order_id, kind, reason=""):
        if kind == "cancel":
            self.cancel_orders([order_id])
            return {"ok": True, "message": "Cancelled (demo)"}
        raise ValueError("Not available in the demo.")

    # -- buying (read-only: nothing can be paid for in the demo) -----------------
    def catalog(self):
        sizes = [(100, 0.49), (500, 1.29), (1000, 2.49), (2500, 5.99), (5000, 9.99), (10000, 14.99)]
        packages = [{"id": str(130 + i), "quantity": q, "price": p, "save": "Save 12%" if q == 5000 else "", "best": q == 5000}
                    for i, (q, p) in enumerate(sizes)]
        return {
            "packages": packages, "delivery": {p["id"]: DELIVERY for p in packages},
            "custom": {"item_id": "132", "min": 500, "max": 100000, "prices": {q: p for q, p in sizes[1:]}},
            "card_minimum": 5.0,
        }

    def quote(self, custom_quantity):
        qty = int(custom_quantity)
        return {"quantity": qty, "price": round(max(0.5, qty * 0.0025), 2), "delivery": DELIVERY}

    def verify_order(self, item_id, link, email, delivery, custom_quantity=None):
        raise ValueError("Demo mode: posts are not checked and nothing can be bought.")

    def more_posts(self, cursor, account=""):
        return {"posts": [], "cursor": None}

    def pay_order(self, *args, **kwargs):
        raise ValueError("Demo mode: payments are disabled.")

    def payment_check(self, *args, **kwargs):
        raise ValueError("Demo mode: payments are disabled.")


def main():
    ui.serve(DemoAutomation(signed_in="--signed-out" not in sys.argv), open_window="--no-window" not in sys.argv)


if __name__ == "__main__":
    main()
