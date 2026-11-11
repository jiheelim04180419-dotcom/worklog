#!/usr/bin/env python3
"""비서 브리핑 재료 모으기 (읽기 전용). 아침·저녁 브리핑 정기 작업이 실행합니다.

  python3 -I .claude/tools/briefing_data.py            # 전부 (공유 메모 + 미입금 + 미청구 + 메일)
  python3 -I .claude/tools/briefing_data.py --no-mail  # 메일 빼고
  python3 -I .claude/tools/briefing_data.py --inv "1650"           # 인보이스 찾기 (번호·빌더·주소 일부)
  python3 -I .claude/tools/briefing_data.py --inv "wattle" --full  # 항목(lineItems)까지

출력은 사람이 읽는 텍스트이고, 화면에만 나옵니다. 저장소에 결과를 커밋하지 않습니다.
인증: FIREBASE_SA_B64 (Firebase), GMAIL_OAUTH_B64 (accounts@/info@ 메일). 없으면 그 부분만 건너뜁니다.
아무 데이터도 고치지 않습니다.
"""
import argparse, base64, json, os, sys, urllib.parse, urllib.request
from datetime import date, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import company_notes as cn  # noqa: E402  (같은 폴더, Firebase 서비스 계정 인증 재사용)

TZ = cn.TZ
TODAY = datetime.now(TZ).date()
OUR_DOMAINS = ("knmtilingbathurst.com", "knmtiling")


# ---------- 인보이스 (앱 invoice/index.html 계산과 맞춤) ----------
def payments(inv):
    p = inv.get("payments")
    if isinstance(p, dict):
        return list(p.values())
    if isinstance(p, list):
        return [x for x in p if x]
    if float(inv.get("depositAmount") or 0) > 0:
        return [{"date": inv.get("depositDate", ""), "amount": float(inv["depositAmount"])}]
    return []


def paid(inv):
    return sum(float(x.get("amount") or 0) for x in payments(inv))


def remaining(inv):
    return round(float(inv.get("amount") or 0) - paid(inv), 2)


def retention_held(inv):
    if inv.get("type") != "PROGRESS" or inv.get("status") in ("PAID", "CREDIT", "DRAFT", "RETENTION"):
        return False
    amt = float(inv.get("amount") or 0)
    rem = remaining(inv)
    return amt > 0 and paid(inv) > 0.01 and amt * 0.02 <= rem <= amt * 0.12


def _biz(d, n):
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _eom(y, m):
    return (date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1))


def contract_due(inv, b):
    term = (b or {}).get("payTerm")
    if not term or not inv.get("invoiceDate"):
        return None
    d = date.fromisoformat(inv["invoiceDate"][:10])
    eom = _eom(d.year, d.month)
    if term == "EOM_NEXT":
        x = _eom(d.year, d.month + 1)
        while x.weekday() >= 5:
            x -= timedelta(days=1)
        return x
    if term == "EOM_30":
        return eom + timedelta(days=30)
    if term == "EOM_BD20":
        return _biz(eom, 20)
    if term == "BD20":
        return _biz(d, 20)
    if term == "D30":
        return d + timedelta(days=30)
    if term == "D14":
        return d + timedelta(days=14)
    if term == "BD10_D30":
        return _biz(d, 10) + timedelta(days=30)
    if term == "FN_FRI":
        x = d + timedelta(days=14)
        a = date(2026, 8, 7)
        k = -(-(x - a).days // 14)
        return a + timedelta(days=14 * k)
    return None


def invoice_section():
    invs = cn._req("GET", "invoices") or {}
    builders = {b.get("name"): b for b in (cn._req("GET", "invoiceBuilders") or {}).values() if isinstance(b, dict)}
    rows, drafts = [], []
    for inv in invs.values():
        if not isinstance(inv, dict):
            continue
        st = inv.get("status")
        if st == "DRAFT":
            drafts.append(inv)
            continue
        if st not in ("INVOICE", "ONGOING", "OVERDUE"):
            continue
        rem = remaining(inv)
        if rem <= 0.01 or retention_held(inv) or not inv.get("invoiceDate"):
            continue
        due = contract_due(inv, builders.get(inv.get("builderName")))
        if not due and inv.get("dueDate"):
            due = date.fromisoformat(inv["dueDate"][:10])
        if not due:
            due = date.fromisoformat(inv["invoiceDate"][:10]) + timedelta(days=30)
        rows.append(((TODAY - due).days, inv, due, rem))
    rows.sort(key=lambda r: -r[0])
    print("## 미입금 인보이스 (기한 지난 것 / 7일 안에 기한)")
    late = [r for r in rows if r[0] > 0]
    soon = [r for r in rows if -7 <= r[0] <= 0]
    for days, inv, due, rem in late:
        chases = inv.get("chases") or {}
        last_chase = max((c.get("date", "") for c in (chases.values() if isinstance(chases, dict) else chases) if isinstance(c, dict)), default="")
        print(f"- {inv.get('invoiceNum')} {inv.get('builderName')} | {inv.get('address','')[:40]} | 잔액 ${rem:,.2f} | 기한 {due} ({days}일 지남)"
              + (f" | 마지막 독촉 {last_chase}" if last_chase else " | 독촉 기록 없음"))
    for days, inv, due, rem in soon:
        print(f"- (곧 기한) {inv.get('invoiceNum')} {inv.get('builderName')} | 잔액 ${rem:,.2f} | 기한 {due}")
    print(f"합계: 기한 지남 {len(late)}건 ${sum(r[3] for r in late):,.2f} / 전체 미입금 {len(rows)}건 ${sum(r[3] for r in rows):,.2f}")
    if drafts:
        print(f"DRAFT(앱에서 확인 필요) {len(drafts)}건: " + ", ".join(str(d.get('invoiceNum')) for d in drafts[:10]))
    print()

    uj = cn._req("GET", "uninvoicedJobs") or {}
    open_jobs = [j for j in uj.values() if isinstance(j, dict) and not j.get("resolved")]
    print("## 미청구 현장 (uninvoicedJobs, 해결 안 된 것)")
    for j in open_jobs:
        print(f"- {j.get('builder')} | {j.get('site')} | 완료 {j.get('completed')} | {j.get('kind')} | {j.get('note','')[:80]}")
    if not open_jobs:
        print("- 없음")
    print()


# ---------- 메일 ----------
def mail_section(days_unanswered=14, hours_new=16):
    raw = os.environ.get("GMAIL_OAUTH_B64")
    if not raw:
        print("## 메일\n- GMAIL_OAUTH_B64 없음: 메일은 Gmail 커넥터로 직접 확인하세요.\n")
        return
    cfg = json.loads(base64.b64decode(raw))
    api = "https://gmail.googleapis.com/gmail/v1/users/me"
    for acct in ("accounts", "info"):
        if acct not in cfg.get("accounts", {}):
            continue
        try:
            data = urllib.parse.urlencode({"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                                           "refresh_token": cfg["accounts"][acct]["refresh_token"],
                                           "grant_type": "refresh_token"}).encode()
            tok = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data))["access_token"]

            def call(path):
                req = urllib.request.Request(api + path, headers={"Authorization": "Bearer " + tok})
                return json.load(urllib.request.urlopen(req, timeout=60))

            q = f"in:inbox newer_than:{days_unanswered}d -category:promotions -category:social -category:forums"
            threads = call("/threads?" + urllib.parse.urlencode({"q": q, "maxResults": 60})).get("threads", [])
            unanswered, new = [], []
            for t in threads:
                th = call(f"/threads/{t['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date&metadataHeaders=Message-ID")
                msgs = th.get("messages", [])
                if not msgs:
                    continue
                last = msgs[-1]
                h = {x["name"].lower(): x["value"] for x in last["payload"].get("headers", [])}
                frm = parseaddr(h.get("from", ""))[1].lower()
                if any(d in frm for d in OUR_DOMAINS) or "SENT" in last.get("labelIds", []):
                    continue  # 우리가 마지막으로 답함
                if "noreply" in frm or "no-reply" in frm or "notification" in frm:
                    continue
                try:
                    when = parsedate_to_datetime(h.get("date")).astimezone(TZ)
                except Exception:
                    when = datetime.fromtimestamp(int(last.get("internalDate", 0)) / 1000, TZ)
                ago_h = (datetime.now(TZ) - when).total_seconds() / 3600
                item = f"- [{when:%m/%d %H:%M}] {h.get('from','')[:50]} | {h.get('subject','')[:80]} | {last.get('snippet','')[:120]} (메시지 {len(msgs)}개) 링크 https://mail.google.com/mail/mu/mp/?authuser={acct}@knmtilingbathurst.com#cv/All%20Mail/{t['id']}"
                (new if ago_h <= hours_new else unanswered).append(item)
            print(f"## 메일 {acct}@ — 최근 {hours_new}시간 새 메일(우리가 아직 답 안 함)")
            print("\n".join(new) if new else "- 없음")
            print(f"## 메일 {acct}@ — {hours_new}시간~{days_unanswered}일 전에 왔는데 아직 답 안 한 메일")
            print("\n".join(unanswered) if unanswered else "- 없음")
            print()
        except Exception as e:  # 한 계정이 실패해도 나머지는 계속
            print(f"## 메일 {acct}@\n- 읽기 실패: {type(e).__name__} {getattr(e, 'code', '')}\n")


def find_invoices(q, full=False):
    q = q.lower()
    invs = [v for v in (cn._req("GET", "invoices") or {}).values() if isinstance(v, dict)]
    hits = [v for v in invs if q in " ".join(str(v.get(k, "")) for k in
                                            ("invoiceNum", "builderName", "address", "projectName", "note")).lower()]
    hits.sort(key=lambda v: v.get("invoiceDate", ""))
    for v in hits[-30:]:
        print(f"{v.get('invoiceNum')} | {v.get('invoiceDate')} | {v.get('builderName')} | {v.get('address','')} | "
              f"{v.get('type','')} {v.get('status')} | 청구 ${float(v.get('amount') or 0):,.2f} | 입금 ${paid(v):,.2f} | "
              f"잔액 ${remaining(v):,.2f}" + (f" | 메모 {v.get('note')}" if v.get("note") else ""))
        if full:
            for it in v.get("lineItems") or []:
                if isinstance(it, dict):
                    print(f"    - {it.get('room','')} {it.get('desc','')} | 이번 {it.get('thisPct','')}% "
                          f"누적 {it.get('cumulativePct','')}% (이전 {it.get('prevPct','')}%) | ${float(it.get('totalAmount') or 0):,.2f}")
            for c in (v.get("chases") or []):
                if isinstance(c, dict):
                    print(f"    독촉 {c.get('date')} {c.get('note','')}")
    print(f"({len(hits)}건 중 최근 {min(len(hits), 30)}건)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--inv", help="인보이스 찾기: 번호·빌더·주소 일부")
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    if a.inv:
        return find_invoices(a.inv, a.full)
    print(f"# 브리핑 재료 — {datetime.now(TZ):%Y-%m-%d %H:%M} (시드니)\n")
    print("## 회사 공유 메모 (claudeNotes, 진행 중)")
    items = cn.all_items()
    act = sorted(((k, n) for k, n in items.items() if isinstance(n, dict) and n.get("status", "active") == "active"),
                 key=lambda kv: kv[1].get("updatedAt", ""), reverse=True)
    for k, n in act:
        print(cn.fmt(k, n))
        print()
    try:
        invoice_section()
    except Exception as e:
        print(f"## 인보이스\n- 읽기 실패: {type(e).__name__} {getattr(e, 'code', '')}\n")
    if not a.no_mail:
        mail_section()


if __name__ == "__main__":
    main()
