#!/usr/bin/env python3
"""K&M 회사 공유 메모 (Firebase `claudeNotes`) — 모든 Claude 프로젝트가 같이 읽고 쓰는 메모.

대화로만 알 수 있는 것 말고, 회사가 알아야 하고 회사에 영향이 있는 사실·결정·진행 중인 일을 적습니다.
비밀번호·키·토큰·계좌/BSB·보험/정책 번호는 절대 적지 않습니다.

  company_notes.py                      진행 중(active) 메모 전체 출력 (세션 시작 때)
  company_notes.py list [--all] [--topic T]
  company_notes.py show <key>
  company_notes.py add --topic T --title "제목" "본문" [--by 프로젝트명]
  company_notes.py update <key> [--title ..] [--body ..] [--append "덧붙일 줄"] [--topic ..] [--by ..]
  company_notes.py done <key> [--by ..]          끝난 일 (목록에서 숨김, 기록은 남김)
  company_notes.py reopen <key>

인증: 환경변수 FIREBASE_SA_B64 (서비스 계정, 클라우드 K&M 환경에 있음). 토큰은 절대 출력하지 않습니다.
데이터 위치: claudeNotes/items/<key> = {topic,title,body,status,createdAt,updatedAt,by}
앱 화면에는 나오지 않고, DB 규칙상 로그인한 관리자/조회 계정 + 서비스 계정만 읽을 수 있습니다.
"""
import argparse, base64, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

DB = "https://knmtilingptyltd-12520-default-rtdb.firebaseio.com"
ROOT = "claudeNotes/items"
SCOPES = "https://www.googleapis.com/auth/firebase.database https://www.googleapis.com/auth/userinfo.email"
TZ = ZoneInfo("Australia/Sydney")
_tok = {}


def _token():
    raw = os.environ.get("FIREBASE_SA_B64")
    if not raw:
        sys.exit("FIREBASE_SA_B64 환경변수가 없습니다 (K&M 환경에서 실행하세요).")
    if _tok.get("exp", 0) > time.time() + 60:
        return _tok["t"]
    sa = json.loads(base64.b64decode(raw))
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


def _req(method, path, body=None):
    u = f"{DB}/{urllib.parse.quote(path.strip('/'))}.json?access_token={_token()}"
    req = urllib.request.Request(u, method=method, headers={"Content-Type": "application/json"},
                                 data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def now():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")


def slug(title):
    s = re.sub(r"[^0-9A-Za-z가-힣]+", "-", title).strip("-").lower()[:40] or "note"
    return f"{datetime.now(TZ).strftime('%Y%m%d')}-{s}"


def all_items():
    return _req("GET", ROOT) or {}


def fmt(k, n, full=True):
    head = f"[{n.get('topic','기타')}] {n.get('title','')}  ({k} · {n.get('updatedAt','')} · {n.get('by','')})"
    if n.get("status") == "done":
        head += "  [끝남]"
    return head + ("\n  " + n.get("body", "").replace("\n", "\n  ") if full else "")


def cmd_list(a):
    items = all_items()
    rows = [(k, n) for k, n in items.items() if (a.all or n.get("status") != "done")
            and (not a.topic or n.get("topic") == a.topic)]
    rows.sort(key=lambda x: (x[1].get("topic", ""), x[1].get("updatedAt", "")))
    if not rows:
        print("(메모 없음)")
    for k, n in rows:
        print(fmt(k, n), end="\n\n")


def need(k):
    n = _req("GET", f"{ROOT}/{k}")
    if not n:
        sys.exit(f"없는 key: {k}")
    return n


def cmd_add(a):
    k = a.key or slug(a.title)
    if _req("GET", f"{ROOT}/{k}"):
        sys.exit(f"이미 있는 key: {k} (update를 쓰세요)")
    t = now()
    n = {"topic": a.topic, "title": a.title, "body": a.body, "status": "active",
         "createdAt": t, "updatedAt": t, "by": a.by}
    _req("PUT", f"{ROOT}/{k}", n)
    print("추가:", k)


def cmd_update(a):
    n = need(a.key)
    p = {"updatedAt": now(), "by": a.by}
    if a.title: p["title"] = a.title
    if a.topic: p["topic"] = a.topic
    if a.body is not None: p["body"] = a.body
    if a.append:
        p["body"] = (p.get("body", n.get("body", "")).rstrip() + f"\n- {now()[:10]}: {a.append}").lstrip()
    _req("PATCH", f"{ROOT}/{a.key}", p)
    print("수정:", a.key)


def cmd_status(a, st):
    need(a.key)
    _req("PATCH", f"{ROOT}/{a.key}", {"status": st, "updatedAt": now(), "by": a.by})
    print(st, a.key)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    by = os.environ.get("KNM_PROJECT", "Claude")
    p = sub.add_parser("list"); p.add_argument("--all", action="store_true"); p.add_argument("--topic")
    p = sub.add_parser("show"); p.add_argument("key")
    p = sub.add_parser("add"); p.add_argument("--topic", required=True); p.add_argument("--title", required=True)
    p.add_argument("--key"); p.add_argument("--by", default=by); p.add_argument("body")
    p = sub.add_parser("update"); p.add_argument("key"); p.add_argument("--title"); p.add_argument("--topic")
    p.add_argument("--body"); p.add_argument("--append"); p.add_argument("--by", default=by)
    for c in ("done", "reopen"):
        p = sub.add_parser(c); p.add_argument("key"); p.add_argument("--by", default=by)
    a = ap.parse_args()
    if a.cmd in (None, "list"):
        if a.cmd is None:
            a.all, a.topic = False, None
        cmd_list(a)
    elif a.cmd == "show":
        print(fmt(a.key, need(a.key)))
    elif a.cmd == "add":
        cmd_add(a)
    elif a.cmd == "update":
        cmd_update(a)
    elif a.cmd == "done":
        cmd_status(a, "done")
    elif a.cmd == "reopen":
        cmd_status(a, "active")


if __name__ == "__main__":
    main()
