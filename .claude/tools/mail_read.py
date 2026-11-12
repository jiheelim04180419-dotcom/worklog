#!/usr/bin/env python3
"""K&M 메일 찾기 (accounts@ + info@ 둘 다) — 읽기 전용. 개발·조회 프로젝트 공용.

Claude의 Gmail 커넥터는 accounts@ 하나만 연결돼 있습니다. info@까지 보려면 이 도구를 씁니다.
인증: env GMAIL_OAUTH_B64. 메일을 보내거나 고치지 않습니다. 토큰은 출력하지 않습니다.

  mail_read.py search "<Gmail 검색어>" [--account all|accounts|info] [--max 20]   (기본: 두 메일함 모두)
  mail_read.py get <accounts|info> <message_id>
  mail_read.py attachments <accounts|info> <message_id> <저장폴더>
"""
import argparse, base64, json, os, urllib.parse, urllib.request

API = "https://gmail.googleapis.com/gmail/v1/users/me"
CFG = json.loads(base64.b64decode(os.environ["GMAIL_OAUTH_B64"]))
_tokens = {}


def token(acct):
    if acct not in _tokens:
        data = urllib.parse.urlencode({
            "client_id": CFG["client_id"], "client_secret": CFG["client_secret"],
            "refresh_token": CFG["accounts"][acct]["refresh_token"],
            "grant_type": "refresh_token"}).encode()
        _tokens[acct] = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data))["access_token"]
    return _tokens[acct]


def call(acct, path):  # GET만 (읽기 전용)
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + token(acct)})
    return json.load(urllib.request.urlopen(req))


def header(msg, name):
    return next((h["value"] for h in msg["payload"].get("headers", []) if h["name"].lower() == name.lower()), "")


def search(q, accts, n):
    for a in accts:
        ids = call(a, "/messages?" + urllib.parse.urlencode({"q": q, "maxResults": n})).get("messages", [])
        for m in ids:
            msg = call(a, f"/messages/{m['id']}?format=metadata&metadataHeaders=From&metadataHeaders=To"
                          "&metadataHeaders=Subject&metadataHeaders=Date")
            print(json.dumps({"account": a, "id": m["id"], "date": header(msg, "Date"), "from": header(msg, "From"),
                              "to": header(msg, "To"), "subject": header(msg, "Subject"),
                              "snippet": msg.get("snippet", "")}, ensure_ascii=False))


def walk(part):
    yield part
    for p in part.get("parts", []) or []:
        yield from walk(p)


def get(acct, mid):
    msg = call(acct, f"/messages/{mid}?format=full")
    text = ""
    for p in walk(msg["payload"]):
        if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
            text += base64.urlsafe_b64decode(p["body"]["data"]).decode(errors="replace")
    files = [p["filename"] for p in walk(msg["payload"]) if p.get("filename")]
    print(json.dumps({"from": header(msg, "From"), "to": header(msg, "To"), "subject": header(msg, "Subject"),
                      "date": header(msg, "Date"), "attachments": files, "body": text}, ensure_ascii=False, indent=1))


def attachments(acct, mid, out):
    os.makedirs(out, exist_ok=True)
    msg = call(acct, f"/messages/{mid}?format=full")
    for p in walk(msg["payload"]):
        aid = p.get("body", {}).get("attachmentId")
        if p.get("filename") and aid:
            d = call(acct, f"/messages/{mid}/attachments/{aid}")["data"]
            path = os.path.join(out, os.path.basename(p["filename"]))
            open(path, "wb").write(base64.urlsafe_b64decode(d))
            print(path)


ap = argparse.ArgumentParser(description="K&M 메일 찾기 (읽기 전용)")
sp = ap.add_subparsers(dest="cmd", required=True)
s = sp.add_parser("search"); s.add_argument("q"); s.add_argument("--account", default="all"); s.add_argument("--max", type=int, default=20)
g = sp.add_parser("get"); g.add_argument("account"); g.add_argument("id")
t = sp.add_parser("attachments"); t.add_argument("account"); t.add_argument("id"); t.add_argument("out")
a = ap.parse_args()

if a.cmd == "search":
    search(a.q, list(CFG["accounts"]) if a.account == "all" else [a.account], a.max)
elif a.cmd == "get":
    get(a.account, a.id)
elif a.cmd == "attachments":
    attachments(a.account, a.id, a.out)
