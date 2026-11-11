#!/usr/bin/env python3
"""새 메일 알림 (accounts@ + info@). 매시간 정기 작업이 실행합니다. 읽기 전용.

  python3 -I .claude/tools/mail_watch.py

지난 실행 뒤 새로 온 받은 메일을 JSON 목록으로 출력합니다 (없으면 NO_NEW_MAIL).
상태 파일: 각 프로젝트의 /mnt/project-files/mail-watch/state.json (env MAIL_WATCH_STATE 로 바꿀 수 있음).
처음 실행하면 최근 2시간치만 봅니다. 광고·소셜·포럼·스팸은 검색에서 뺍니다.
info@ 메일 중 accounts@ 에도 같이 온 것은 accounts@ 쪽에서만 보고합니다.
인증: env GMAIL_OAUTH_B64. 메일을 고치거나 보내지 않습니다.
"""
import base64, json, os, re, time, urllib.parse, urllib.request

DOMAIN = "knmtilingbathurst.com"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
CFG = json.loads(base64.b64decode(os.environ["GMAIL_OAUTH_B64"]))
SP = os.environ.get("MAIL_WATCH_STATE", "/mnt/project-files/mail-watch/state.json")
Q = "newer_than:3d -in:sent -in:drafts -in:spam -in:trash -category:promotions -category:social -category:forums"
_tok = {}


def call(acct, path):
    if acct not in _tok:
        data = urllib.parse.urlencode({"client_id": CFG["client_id"], "client_secret": CFG["client_secret"],
                                       "refresh_token": CFG["accounts"][acct]["refresh_token"],
                                       "grant_type": "refresh_token"}).encode()
        _tok[acct] = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data))["access_token"]
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + _tok[acct]})
    return json.load(urllib.request.urlopen(req, timeout=60))


def gmail_link(acct, thread_id):
    """폰에서 누르면 Gmail 앱으로 그 메일 대화가 열리는 링크 (go/gmail.html 이 googlegmail:// 로 넘김)."""
    return f"https://jiheelim04180419-dotcom.github.io/worklog/go/gmail.html?a={acct}&t={thread_id}"


def text(p):
    out = ""
    if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
        out += base64.urlsafe_b64decode(p["body"]["data"]).decode(errors="replace")
    for c in p.get("parts", []) or []:
        out += text(c)
    return out


def files(p, acc):
    if p.get("filename"):
        acc.append(p["filename"])
    for c in p.get("parts", []) or []:
        files(c, acc)
    return acc


def main():
    st = json.load(open(SP)) if os.path.exists(SP) else {}
    seen = set(st.get("seen", []))
    since = st.get("since_ms") or int(time.time() * 1000) - 2 * 3600 * 1000
    accts = st.get("accounts_watched") or [a for a in ("accounts", "info") if a in CFG.get("accounts", {})]
    new = []
    for acct in accts:
        for m in call(acct, "/messages?" + urllib.parse.urlencode({"q": Q, "maxResults": 100})).get("messages", []):
            key = f"{acct}:{m['id']}"
            if key in seen:
                continue
            seen.add(key)
            msg = call(acct, f"/messages/{m['id']}?format=full")
            if int(msg["internalDate"]) < since:
                continue
            h = {x["name"].lower(): x["value"] for x in msg["payload"].get("headers", [])}
            frm = h.get("from", "")
            if DOMAIN in frm.lower() and acct + "@" in frm.lower():
                continue  # 우리가 보낸 것
            if acct == "info" and f"accounts@{DOMAIN}" in (str(h.get("to", "")) + str(h.get("cc", ""))).lower():
                continue  # accounts@ 쪽에서 보고
            if "list-unsubscribe" in h and h.get("precedence", "").lower() in ("bulk", "list"):
                continue
            body = re.split(r"\n(From:|On .{5,80}wrote:|-----Original Message)", text(msg["payload"]))[0]
            att = [f for f in files(msg["payload"], []) if not re.match(r"(image\d+|Outlook-|[0-9a-f-]{36})", f)]
            new.append({"account": acct, "id": m["id"], "threadId": msg["threadId"],
                        "link": gmail_link(acct, msg["threadId"]), "date": h.get("date"),
                        "from": frm, "to": h.get("to"), "cc": h.get("cc"), "subject": h.get("subject"),
                        "labels": msg.get("labelIds", []), "bulk": "list-unsubscribe" in h,
                        "attachments": att, "body": re.sub(r"\s+", " ", body)[:2000]})
    st.update(seen=sorted(seen)[-3000:], accounts_watched=accts,
              since_ms=max(since, int(time.time() * 1000) - 3 * 86400 * 1000),
              last_run=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    os.makedirs(os.path.dirname(SP), exist_ok=True)
    json.dump(st, open(SP, "w"))
    print(json.dumps(new, ensure_ascii=False, indent=1) if new else "NO_NEW_MAIL")


if __name__ == "__main__":
    main()
