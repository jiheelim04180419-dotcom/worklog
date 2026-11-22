#!/usr/bin/env python3
"""K&M 메일 초안 만들기 (accounts@ / info@) — 개발·조회 프로젝트 공용.

Gmail 커넥터는 accounts@만 연결돼 있어서, info@ 메일은 이 도구로 씁니다.
인증: env GMAIL_OAUTH_B64. 토큰은 출력하지 않습니다.
서명: Gmail의 실제 서명(HTML, 로고 포함)과 보낸 사람 이름을 그대로 붙입니다.
  --sign 이름 : 그 사람이 이 메일함에서 마지막으로 보낸 메일의 서명(맺음말 포함)을 그대로 씁니다.
               예) --sign Kyle, --sign Max, --sign Sarah. info@는 --sign 이 없으면 Kyle.
               --sign default 는 Gmail 설정의 기본 서명. 본문에 "Kind regards, 이름"은 쓰지 마세요.

  새 메일:  mail_draft.py new <accounts|info> --to a@b --subject "제목" --body-file 본문.txt [--cc x] [--attach f.pdf ...]
  답장:     mail_draft.py reply <accounts|info> <message_id> --body-file 본문.txt [--all] [--cc x] [--attach f ...]
            (--all = 전체 답장, 원래 참조 유지. message_id는 mail_read.py search 결과의 id)
  초안 보기: mail_draft.py show <accounts|info> <draft_id>
  초안 지우기: mail_draft.py delete <accounts|info> <draft_id>
  보내기:   mail_draft.py send <accounts|info> <draft_id> --ok
            회사 규칙: 초안을 먼저 보여주고 사람이 OK한 뒤에만 보냅니다. --ok 없이는 보내지 않습니다.
"""
import argparse, base64, html, json, mimetypes, os, re, sys, urllib.parse, urllib.request
from email.message import EmailMessage
from email.utils import getaddresses

API = "https://gmail.googleapis.com/gmail/v1/users/me"
CFG = json.loads(base64.b64decode(os.environ["GMAIL_OAUTH_B64"]))
_tok = {}


def token(acct):
    if acct not in _tok:
        data = urllib.parse.urlencode({
            "client_id": CFG["client_id"], "client_secret": CFG["client_secret"],
            "refresh_token": CFG["accounts"][acct]["refresh_token"],
            "grant_type": "refresh_token"}).encode()
        _tok[acct] = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data))["access_token"]
    return _tok[acct]


def call(acct, path, body=None, method=None):
    req = urllib.request.Request(
        API + path, method=method or ("POST" if body is not None else "GET"),
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + token(acct), "Content-Type": "application/json"})
    r = urllib.request.urlopen(req).read()
    return json.loads(r) if r else {}


def me(acct):
    return CFG["accounts"][acct]["email"]


def signature(acct):
    for s in call(acct, "/settings/sendAs")["sendAs"]:
        if s["sendAsEmail"].lower() == me(acct).lower():
            return s.get("signature", ""), s.get("displayName", "") or last_sent_name(acct)
    return "", last_sent_name(acct)


def last_sent_name(acct):  # Gmail에 표시 이름 설정이 없으면, 최근 보낸 메일의 이름을 그대로 씀
    ids = call(acct, "/messages?q=in%3Asent&maxResults=1").get("messages", [])
    if not ids:
        return ""
    msg = call(acct, f"/messages/{ids[0]['id']}?format=metadata&metadataHeaders=From")
    frm = next((h["value"] for h in msg["payload"]["headers"] if h["name"] == "From"), "")
    return getaddresses([frm])[0][0] if frm else ""


DEFAULT_SIGN = {"info": "Kyle"}  # info@는 요즘 거의 카일이 씀 (Kathleen 2026-11-23)


def html_part(msg):
    for p in walk(msg["payload"]):
        if p.get("mimeType") == "text/html" and p.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(p["body"]["data"]).decode(errors="replace")
    return ""


def walk(part):
    yield part
    for p in part.get("parts", []) or []:
        yield from walk(p)


def sig_div(h):  # 내가 쓴 부분(인용 앞)의 gmail_signature div 전체
    h = h.split('class="gmail_quote')[0]
    i = h.find("gmail_signature")
    if i < 0:
        return None, h
    start = h.rfind("<div", 0, i)
    depth, j = 0, start
    for m in re.finditer(r"<(/?)div\b[^>]*>", h[start:]):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            j = start + m.end()
            break
    else:
        j = len(h)
    return h[start:j], h[:start]


def text_of(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


def person_signature(acct, who):
    """그 사람이 마지막으로 보낸 메일에서 서명 HTML과 (서명 밖에 쓴) 맺음말을 가져옴."""
    ids = call(acct, "/messages?" + urllib.parse.urlencode({"q": f'in:sent "{who}"', "maxResults": 25})).get("messages", [])
    for m in ids:
        sig, before = sig_div(html_part(call(acct, f"/messages/{m['id']}?format=full")))
        if not sig:
            continue
        if re.search(rf"\b{re.escape(who)}\b", text_of(sig), re.I):
            return sig, ""
        tail = re.search(rf"((?:Kind regards|Best regards|Regards|Thanks|Cheers)[^<>]{{0,3}}(?:\s|<[^>]+>)*{re.escape(who)}\b.*)$",
                         before, re.I | re.S)
        if tail:
            lines = [l.strip() for l in re.split(r"<br\s*/?>|</div>|\n", tail.group(1)) if text_of(l)]
            return sig, "\n".join(text_of(l) for l in lines[:4])
    sys.exit(f"{acct}@ 보낸메일에서 {who}의 서명을 못 찾았습니다. 서명을 손으로 만들지 말고 사람에게 물어보세요.")


def build(acct, text, to, subject, cc=None, attach=(), sign=None):
    sig, name = signature(acct)
    who = sign or DEFAULT_SIGN.get(acct)
    signoff = ""
    if who and who.lower() != "default":
        sig, signoff = person_signature(acct, who)
    if signoff:
        text = text.rstrip() + "\n\n" + signoff
    if not sig:
        sys.exit(f"{acct}@ 메일함에 Gmail 서명이 없습니다. 서명을 손으로 넣지 말고 Kathleen/Max에게 알려 주세요.")
    m = EmailMessage()
    m["From"] = f"{name} <{me(acct)}>" if name else me(acct)
    m["To"], m["Subject"] = to, subject
    if cc:
        m["Cc"] = cc
    m.set_content(text)
    m.add_alternative("<div>" + "<br>".join(html.escape(l) for l in text.splitlines()) + "</div>"
                      + '<br><div class="gmail_signature">' + sig + "</div>", subtype="html")
    m.signer = f"{who or 'default'}: {text_of(sig)[:60]}"
    for f in attach or []:
        main, sub = (mimetypes.guess_type(f)[0] or "application/octet-stream").split("/", 1)
        m.add_attachment(open(f, "rb").read(), maintype=main, subtype=sub, filename=os.path.basename(f))
    return m


def save(acct, m, thread=None):
    msg = {"raw": base64.urlsafe_b64encode(m.as_bytes()).decode()}
    if thread:
        msg["threadId"] = thread
    d = call(acct, "/drafts", {"message": msg})
    print(json.dumps({"draft_id": d["id"], "account": acct, "from": m["From"], "to": m["To"], "cc": m["Cc"],
                      "subject": m["Subject"], "thread": thread, "sign": getattr(m, "signer", ""),
                      "attach": [p.get_filename() for p in m.iter_attachments()]}, ensure_ascii=False))


def cmd_new(a):
    save(a.account, build(a.account, open(a.body_file).read(), a.to, a.subject, a.cc, a.attach, a.sign))


def cmd_reply(a):
    o = call(a.account, f"/messages/{a.id}?format=metadata" + "".join(
        "&metadataHeaders=" + h for h in ("Message-ID", "Subject", "From", "To", "Cc", "Reply-To", "References")))
    h = {x["name"].lower(): x["value"] for x in o["payload"]["headers"]}
    mine = me(a.account).lower()
    to = h.get("reply-to") or h["from"]
    if mine in to.lower():  # 내가 보낸 메일에 다시 답장하면 원래 받는 사람에게
        to = h.get("to", "")
    cc = []
    if a.all:
        for _, addr in getaddresses([h.get("to", ""), h.get("cc", "")]):
            if addr and addr.lower() != mine and addr.lower() not in to.lower():
                cc.append(addr)
    if a.cc:
        cc.append(a.cc)
    subj = h.get("subject", "")
    m = build(a.account, open(a.body_file).read(), to,
              subj if subj.lower().startswith("re:") else "Re: " + subj, ", ".join(cc) or None, a.attach, a.sign)
    m["In-Reply-To"] = h["message-id"]
    m["References"] = (h.get("references", "") + " " + h["message-id"]).strip()
    save(a.account, m, o["threadId"])


def cmd_show(a):
    d = call(a.account, f"/drafts/{a.id}?format=full")["message"]
    h = {x["name"]: x["value"] for x in d["payload"]["headers"] if x["name"] in ("From", "To", "Cc", "Subject")}
    print(json.dumps({**h, "snippet": d.get("snippet", "")}, ensure_ascii=False, indent=1))


def cmd_delete(a):
    call(a.account, f"/drafts/{a.id}", method="DELETE")
    print(json.dumps({"deleted": a.id}))


def cmd_send(a):
    if not a.ok:
        sys.exit("보내지 않았습니다: 사람이 초안을 보고 OK한 뒤 --ok 를 붙여 다시 실행하세요.")
    r = call(a.account, "/drafts/send", {"id": a.id})
    print(json.dumps({"sent_message_id": r.get("id"), "thread": r.get("threadId")}))


ap = argparse.ArgumentParser(description="K&M 메일 초안 (accounts@/info@)")
sp = ap.add_subparsers(dest="cmd", required=True)
acct = {"choices": ["accounts", "info"]}
n = sp.add_parser("new"); n.add_argument("account", **acct); n.add_argument("--to", required=True)
n.add_argument("--subject", required=True); n.add_argument("--body-file", required=True)
n.add_argument("--cc"); n.add_argument("--attach", nargs="*"); n.add_argument("--sign")
r = sp.add_parser("reply"); r.add_argument("account", **acct); r.add_argument("id"); r.add_argument("--body-file", required=True)
r.add_argument("--all", action="store_true"); r.add_argument("--cc"); r.add_argument("--attach", nargs="*"); r.add_argument("--sign")
for c in ("show", "delete", "send"):
    p = sp.add_parser(c); p.add_argument("account", **acct); p.add_argument("id")
    if c == "send":
        p.add_argument("--ok", action="store_true")
a = ap.parse_args()
{"new": cmd_new, "reply": cmd_reply, "show": cmd_show, "delete": cmd_delete, "send": cmd_send}[a.cmd](a)
