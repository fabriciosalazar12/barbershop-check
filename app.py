import os, time
from collections import OrderedDict
from flask import Flask, request, jsonify, send_from_directory
import stripe
from dotenv import load_dotenv

# carrega .env
load_dotenv(override=True)

stripe.api_key = os.environ.get("STRIPE_API_KEY")
if not stripe.api_key:
    raise RuntimeError("Missing STRIPE_API_KEY in environment.")

ALLOW_OK = {"active", "trialing"}

app = Flask(__name__, static_folder="public", static_url_path="/")

class TTLCache(OrderedDict):
    def __init__(self, maxlen=512, ttl=90):
        super().__init__(); self.maxlen, self.ttl = maxlen, ttl
    def get_cached(self, key):
        now = time.time()
        if key in self:
            val, ts = super().__getitem__(key)
            if now - ts <= self.ttl: return val
            else: super().__delitem__(key)
        return None
    def set_cached(self, key, val):
        now = time.time(); super().__setitem__(key, (val, now))
        if len(self) > self.maxlen: self.popitem(last=False)

cache = TTLCache()

@app.get("/check")
def check_page():
    return send_from_directory("public", "check.html")

@app.get("/api/subscription/verify-by-email")
def verify_by_email():
    email = (request.args.get("email") or "").strip().lower()
    if not email:
        return jsonify(ok=False, reason="missing_email"), 400

    cached = cache.get_cached(email)
    if cached is not None:
        return jsonify(**cached)

    try:
        customers = stripe.Customer.search(query=f"email:'{email}'", limit=10)
        if not customers.data:
            res = dict(ok=False, reason="customer_not_found")
            cache.set_cached(email, res); return jsonify(**res)

        best = None
        for c in customers.auto_paging_iter():
            subs = stripe.Subscription.list(customer=c.id, status="all", limit=20)
            for s in subs.auto_paging_iter():
                if s.status in ALLOW_OK:
                    best = dict(ok=True, name=c.get("name") or c.get("email"), status=s.status)
                    break
            if best: break

        if best:
            cache.set_cached(email, best); return jsonify(**best)
        else:
            res = dict(ok=False, reason="no_active_subscription")
            cache.set_cached(email, res); return jsonify(**res)

    except stripe.error.AuthenticationError:
        return jsonify(ok=False, reason="invalid_stripe_key"), 500
    except Exception as e:
        print("verify-by-email error:", e)
        return jsonify(ok=False, reason="internal_error"), 500

@app.get("/")
def root():
    return send_from_directory("public", "check.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
