#!/usr/bin/env python3
"""Firebase Realtime DB helper for K&M (cloud side).

Auth: if env FIREBASE_SA_B64 (base64 of the service-account JSON) is set, every
request carries an OAuth access token (admin access, bypasses rules). Without it,
requests go unauthenticated (works only while DB rules are open).

  firebase_rest.py get <path> [--shallow]      print JSON
  firebase_rest.py put|patch <path> <json-file>
  firebase_rest.py backup [--keep 30]          full DB -> /mnt/project-files/backups/firebase/knm-YYYYMMDD-HHMM.json.gz
  firebase_rest.py token                       print "ok <sa email>" (never the token)

As a module: from firebase_rest import url, get, put, patch
Never print the token or the key.
"""
import base64, gzip, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

DB = "https://knmtilingptyltd-12520-default-rtdb.firebaseio.com"
BACKUP_DIR = "/mnt/project-files/backups/firebase"
SCOPES = "https://www.googleapis.com/auth/firebase.database https://www.googleapis.com/auth/userinfo.email"
_tok = {}


def _sa():
    raw = os.environ.get("FIREBASE_SA_B64")
    return json.loads(base64.b64decode(raw)) if raw else None


def access_token():
    sa = _sa()
    if not sa:
        return None
    if _tok.get("exp", 0) > time.time() + 60:
        return _tok["t"]
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
    now = int(time.time())
    claims = {"iss": sa["client_email"], "scope": SCOPES, "aud": "https://oauth2.googleapis.com/token",
              "iat": now, "exp": now + 3600}
    signing = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()) + b"." + b64(json.dumps(claims).encode())
    key = serialization.load_pem_private_key(sa["private_key"].encode(), None)
    jwt = signing + b"." + b64(key.sign(signing, padding.PKCS1v15(), hashes.SHA256()))
    data = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": jwt.decode()}).encode()
    r = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data))
    _tok.update(t=r["access_token"], exp=now + int(r.get("expires_in", 3600)))
    return _tok["t"]


def url(path, **params):
    t = access_token()
    if t:
        params["access_token"] = t
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    return f"{DB}/{path.strip('/')}.json{q}"


def _req(method, path, body=None, **params):
    req = urllib.request.Request(url(path, **params), method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def get(path, **params): return _req("GET", path, **params)
def put(path, body): return _req("PUT", path, body)
def patch(path, body): return _req("PATCH", path, body)


def backup(keep=30):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(ZoneInfo("Australia/Sydney")).strftime("%Y%m%d-%H%M")
    with urllib.request.urlopen(url(""), timeout=300) as r:
        raw = r.read()
    data = json.loads(raw)
    if not isinstance(data, dict) or "invoices" not in data:
        raise SystemExit("backup FAILED: unexpected response")
    out = f"{BACKUP_DIR}/knm-{stamp}.json.gz"
    with gzip.open(out, "wb") as f:
        f.write(raw)
    files = sorted(n for n in os.listdir(BACKUP_DIR) if n.startswith("knm-") and n.endswith(".json.gz"))
    for old in files[:-keep]:
        os.remove(f"{BACKUP_DIR}/{old}")
    counts = {k: len(v) if isinstance(v, (dict, list)) else 1 for k, v in data.items()}
    print(f"backup ok {out} {os.path.getsize(out)//1024}KB invoices={counts.get('invoices')} "
          f"logs={counts.get('logs')} kept={min(len(files), keep)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "get":
        print(json.dumps(get(a[1], **({"shallow": "true"} if "--shallow" in a else {})), ensure_ascii=False, indent=1))
    elif cmd in ("put", "patch"):
        body = json.load(open(a[2]))
        print(json.dumps((put if cmd == "put" else patch)(a[1], body), ensure_ascii=False)[:500])
    elif cmd == "backup":
        backup(int(a[a.index("--keep") + 1]) if "--keep" in a else 30)
    elif cmd == "token":
        sa = _sa()
        print(f"ok {sa['client_email']}" if sa and access_token() else "no FIREBASE_SA_B64 (unauthenticated mode)")
    else:
        sys.exit(__doc__)
