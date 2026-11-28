#!/usr/bin/env python3
"""Make an accounts@ Gmail draft for an issued invoice: invoice PDF (+ Statement if the builder
needs one) rendered by the real invoice app, plus the accounts@ Gmail signature.

  invoice_draft.py INV-1659 [--to x@y] [--cc a@b] [--notice auto|yes|no]
  invoice_draft.py --send <draft_id>          # only after Max says OK

Needs a session NOT linked to Max's Mac (linked sessions block googleapis.com) and env GMAIL_OAUTH_B64.
"""
import argparse, base64, datetime, html, json, os, re, subprocess, sys, tempfile, urllib.parse, urllib.request
from email.message import EmailMessage
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); import firebase_rest  # noqa: E402
API = "https://gmail.googleapis.com/gmail/v1/users/me"
CFG = json.loads(base64.b64decode(os.environ["GMAIL_OAUTH_B64"]))
ACCT = "accounts"
_tok = None


def call(path, body=None):
    global _tok
    if not _tok:
        a = CFG["accounts"][ACCT]
        data = urllib.parse.urlencode({"client_id": CFG["client_id"], "client_secret": CFG["client_secret"],
                                       "refresh_token": a["refresh_token"], "grant_type": "refresh_token"}).encode()
        _tok = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data))["access_token"]
    req = urllib.request.Request(API + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + _tok, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def signature():
    me = CFG["accounts"][ACCT]["email"].lower()
    for s in call("/settings/sendAs").get("sendAs", []):
        if s["sendAsEmail"].lower() == me:
            return s.get("signature", ""), s.get("displayName", "")
    return "", ""


# Builders whose claims also go through another program (tell Max before mailing).
PORTALS = {"baseline": "Payapps claim + Work Comp package", "akura": "Premier portal claim",
           "maas": "Premier portal claim (TWPZ; small jobs like J950 Baillie St are email only)",
           "stanaway": "Premier portal claim (TWPZ; small jobs like J950 Baillie St are email only)"}


# Sites whose invoice mail must also CC someone (matched on project name / address, lower case).
# Kept in Firebase claudeMeta/invoiceMail/siteCc as {match word: address} (this repo is public).
def site_cc(info):
    s = f"{info.get('projectName') or ''} {info.get('address') or ''}".lower()
    rules = firebase_rest.get("claudeMeta/invoiceMail/siteCc") or {}
    return ", ".join(v for k, v in rules.items() if k in s)


def portal_note(builder):
    b = (builder or "").lower()
    return next((v for k, v in PORTALS.items() if k in b), "")


# Company rename notice (Max 2026-11-26): the first invoice mail to each builder under the new name
# says the name changed. Who got it is kept in Firebase claudeMeta/renameNotice (shared by every
# Claude project): "pending" = drafts made, "notified" = recorded on --send.
NOTICE_PATH = "claudeMeta/renameNotice"
RENAME_NOTICE = ("Please note that our company name has changed from K&M Tiling Bathurst Pty Ltd "
                 "to K&M Tiling Pty Ltd. Our ABN and bank details remain the same.")


def fb_key(s):
    return re.sub(r"[.$#\[\]/\s]+", "_", s.strip().lower()) or "_"


def notice_state():
    st = firebase_rest.get(NOTICE_PATH) or {}
    return {"notified": st.get("notified") or {}, "pending": st.get("pending") or {}}


def already_sent(inv):
    q = urllib.parse.quote(f"in:sent filename:{inv}.pdf")
    hits = []
    for m in call(f"/messages?q={q}&maxResults=5").get("messages", []):
        h = {x["name"]: x["value"] for x in call(f"/messages/{m['id']}?format=metadata&metadataHeaders=Date&metadataHeaders=To")["payload"]["headers"]}
        hits.append({"date": h.get("Date"), "to": h.get("To")})
    return hits


ap = argparse.ArgumentParser()
ap.add_argument("inv", nargs="?")
ap.add_argument("--to"); ap.add_argument("--cc")
ap.add_argument("--repo", default=os.path.abspath(os.path.join(HERE, "..", "..", "..")))
ap.add_argument("--send")
ap.add_argument("--notice", choices=["auto", "yes", "no"], default="auto")
a = ap.parse_args()

if a.send:
    r = call("/drafts/send", {"id": a.send})
    p = notice_state()["pending"].get(fb_key(a.send))
    if p:
        firebase_rest.put(f"{NOTICE_PATH}/notified/{p['builder']}",
                          {"name": p.get("name", ""), "inv": p["inv"], "date": datetime.date.today().isoformat()})
        firebase_rest._req("DELETE", f"{NOTICE_PATH}/pending/{fb_key(a.send)}")
    print(json.dumps({"sent_message_id": r.get("id"), "threadId": r.get("threadId")}))
    sys.exit(0)

out = tempfile.mkdtemp(prefix=a.inv + "-")
# Firebase 읽기용 서비스 계정 토큰 (DB 규칙이 잠겨도 동작). 환경변수로만 전달, 출력 금지.
_env = dict(os.environ, FB_ACCESS_TOKEN=firebase_rest.access_token() or "")
r = subprocess.run(["node", os.path.join(HERE, "render_pdfs.js"), a.repo, os.path.join(HERE, "libs"), a.inv, out],
                   capture_output=True, text=True, timeout=300, env=_env)
if r.returncode:
    sys.exit("render failed: " + (r.stdout + r.stderr)[-1500:])
info = json.loads(r.stdout)
to = a.to or info["to"]
if not to:
    sys.exit("no invoice email for builder " + info["builderName"] + "; pass --to")

today = datetime.datetime.now(ZoneInfo("Australia/Sydney")).strftime("%d/%m/%y")
co_short = info["companyName"].replace("PTY LTD", "").replace("Pty Ltd", "").strip()
subject = f"Payment request {today} {co_short}"
ref = info["projectName"] or info["address"] or "—"
bkey = fb_key(info.get("builderName") or "")
st = notice_state()
new_name = "bathurst" not in info["companyName"].lower()
notice = a.notice == "yes" or (a.notice == "auto" and new_name and bkey not in st["notified"])
text = (f"Hello,\n\nPlease find the attached invoice below for {ref}.\n"
        + (RENAME_NOTICE + "\n" if notice else "")
        + "If you have any questions, please do not hesitate to contact us.\n")
sig_html, display = signature()
body_html = "<div>" + "<br>".join(html.escape(l) for l in text.splitlines()) + "</div>"
if sig_html:
    body_html += '<br><div class="gmail_signature">' + sig_html + "</div>"

m = EmailMessage()
frm = CFG["accounts"][ACCT]["email"]
m["From"] = f"{display or 'Kathleen Lim'} <{frm}>"
m["To"], m["Subject"] = to, subject
cc = ", ".join(x for x in (a.cc, site_cc(info)) if x)
if cc:
    m["Cc"] = cc
m.set_content(text)
m.add_alternative(body_html, subtype="html")
for f in info["files"]:
    m.add_attachment(open(f, "rb").read(), maintype="application", subtype="pdf", filename=os.path.basename(f))
d = call("/drafts", {"message": {"raw": base64.urlsafe_b64encode(m.as_bytes()).decode()}})
if notice:
    firebase_rest.put(f"{NOTICE_PATH}/pending/{fb_key(d['id'])}",
                      {"builder": bkey, "name": info.get("builderName") or "", "inv": a.inv})
print(json.dumps({"draft_id": d["id"], "from": m["From"], "to": to, "cc": cc, "subject": subject,
                  "body": text, "rename_notice": notice, "signature_found": bool(sig_html), "attachments": [os.path.basename(f) for f in info["files"]],
                  "invoice": {k: info.get(k) for k in ("invoiceNum", "builderName", "status", "amount", "needsWorkComp")},
                  "already_sent": already_sent(a.inv), "portal": portal_note(info.get("builderName")), "pdf_dir": out}, ensure_ascii=False, indent=1))
