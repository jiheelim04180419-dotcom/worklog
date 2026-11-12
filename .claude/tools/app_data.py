#!/usr/bin/env python3
"""K&M 회사 앱 3개(WorkLog·인보이스·SiteLog) 데이터 읽기 — 읽기 전용. 개발·조회 프로젝트 공용.

관리자가 앱에서 보는 정보는 모두 Firebase 한 곳에 있으므로, 서비스 계정(FIREBASE_SA_B64)으로 그대로 읽습니다.
이 도구는 아무것도 고치지 않습니다. 토큰·비밀값은 출력하지 않습니다.

  app_data.py paths                          앱별 Firebase 경로 지도
  app_data.py keys <경로>                    그 경로 아래 키 목록 (가볍게)
  app_data.py get <경로> [--last N]          JSON 출력 (--last: 키 순서로 마지막 N개만)
  app_data.py find <경로> "검색어"           그 경로 아래에서 글자가 들어간 항목 찾기
  app_data.py logs [--from YYYY-MM-DD] [--to ..] [--who 이름/ID]   WorkLog 일지 (기본: 최근 7일)
  app_data.py sitelog [--days N] [--site 검색어]                   SiteLog 최근 게시물 (기본: 7일)
  app_data.py board                          현장 현황판(siteBoard) 요약

인보이스는 briefing_data.py --inv 1650 처럼 찾는 것이 더 편합니다.
"""
import argparse, json, os, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import company_notes as cn  # 같은 인증/DB 주소 재사용

PATHS = {
    "WorkLog (index.html) — 일지·급여·직원": {
        "logs": "작업 일지 (date, userId, hours, status, workType, travel, content)",
        "users": "직원 (이름, 역할, 입사일, 비자, 생일 — 관리자 전용 정보)",
        "staffDirectory": "직원 목록 (생년은 일부러 2000으로 저장됨, 나이 판단에 쓰지 말 것)",
        "leaves": "휴가", "payLocks": "급여 마감 잠금 날짜", "recurringDeductions": "정기 공제",
        "personalCardEntries": "개인카드 사용", "vehicles": "차량", "mgmt": "관리 설정",
        "partnerLedger": "파트너 장부", "loginIndex / authMap": "로그인 연결 (읽을 일 거의 없음)",
    },
    "인보이스 (invoice/index.html) — 청구·입금·지출·발주": {
        "invoices": "인보이스 (번호, 빌더, 금액, 상태, 입금 payments, 독촉 chases)",
        "invoiceBuilders": "빌더 설정 (입금 조건 등)", "invoiceCompanies": "회사 정보", "invoiceRooms": "방/항목 템플릿",
        "invoiceUsers": "인보이스 앱 사용자", "builderNames": "빌더 이름",
        "monthlyPayments": "정기 지출 탭 (월말 공급업체 지급)", "expenseVendors": "지출 거래처",
        "astroOrders": "아스트로 발주", "remittanceDrafts": "레미턴스 요청",
        "uninvoicedJobs": "미청구 작업", "companies": "회사",
    },
    "SiteLog (photos/index.html) — 현장 사진·현황판": {
        "photoApp/projects": "현장 목록 (이름, 빌더, 주소, 마지막 활동)",
        "photoApp/entries/<현장ID>": "현장별 게시물 (사진, 메모, 작성자, 날짜, 댓글)",
        "siteBoard / siteBoardMoney / siteBoardQuotePdf": "현장 현황판 (일정, 금액, 견적 PDF)",
    },
    "Claude 공용": {"claudeNotes": "회사 공유 메모 (company_notes.py로 읽고 쓰기)"},
}


def _get(path, **q):
    q = {k: (json.dumps(v) if k in ("orderBy", "startAt", "endAt", "equalTo") else v) for k, v in q.items()}
    q["access_token"] = cn._token()
    u = f"{cn.DB}/{urllib.parse.quote(path.strip('/'))}.json?{urllib.parse.urlencode(q)}"
    with urllib.request.urlopen(u, timeout=120) as r:
        return json.load(r)


def _out(x):
    print(json.dumps(x, ensure_ascii=False, indent=1))


def _ms(d):
    return int(datetime.strptime(d, "%Y-%m-%d").timestamp() * 1000)


def _date(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except Exception:
        return "?"


def cmd_logs(a):
    to = a.to or datetime.now().strftime("%Y-%m-%d")
    fr = a.frm or (datetime.strptime(to, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        data = _get("logs", orderBy="date", startAt=fr, endAt=to) or {}
    except Exception:  # 색인이 없으면 전부 받아서 거르기
        data = {k: v for k, v in (_get("logs") or {}).items() if isinstance(v, dict) and fr <= v.get("date", "") <= to}
    rows = sorted((v for v in data.values() if isinstance(v, dict)), key=lambda v: (v.get("date", ""), v.get("userId", "")))
    if a.who:
        w = a.who.lower()
        rows = [v for v in rows if w in str(v.get("userId", "")).lower() or w in str(v.get("modifiedByName", "")).lower()]
    print(f"WorkLog 일지 {fr} ~ {to}: {len(rows)}건")
    for v in rows:
        t = v.get("travel") or {}
        extra = " 출장" if t.get("isBizTrip") else ""
        print(f"{v.get('date')} {v.get('userId','?'):<10} {v.get('status','')} {v.get('startTime','')}-{v.get('endTime','')} "
              f"{v.get('hours','')}h{extra} {v.get('content','')}".rstrip())


def cmd_sitelog(a):
    since = int((datetime.now() - timedelta(days=a.days)).timestamp() * 1000)
    projs = _get("photoApp/projects") or {}
    n = 0
    for pid, p in sorted(projs.items(), key=lambda kv: -(kv[1].get("lastActivity") or 0) if isinstance(kv[1], dict) else 0):
        if not isinstance(p, dict) or (p.get("lastActivity") or 0) < since:
            continue
        if a.site and a.site.lower() not in (p.get("name", "") + p.get("address", "")).lower():
            continue
        ents = _get(f"photoApp/entries/{pid}") or {}
        recent = sorted((e for e in ents.values() if isinstance(e, dict) and (e.get("date") or 0) >= since),
                        key=lambda e: e.get("date") or 0)
        if not recent:
            continue
        print(f"\n■ {p.get('name')} ({p.get('address','')})")
        for e in recent:
            n += 1
            kind = "메모" if e.get("category") == "__notes__" else (e.get("category") or "")
            nph = len(e.get("photos") or [])
            txt = (e.get("text") or e.get("note") or e.get("caption") or "").replace("\n", " ")[:120]
            nc = len(e.get("comments") or {})
            print(f"  {_date(e.get('date'))} {e.get('authorName','?')} [{kind}] 사진 {nph}장"
                  f"{' 댓글 '+str(nc) if nc else ''} {txt}".rstrip())
    print(f"\nSiteLog 최근 {a.days}일 게시물 {n}건")


def cmd_board(a):
    b = _get("siteBoard") or {}
    projs = _get("photoApp/projects") or {}  # 현황판 키 = SiteLog 현장 ID
    for k, v in b.items():
        if not isinstance(v, dict):
            continue
        p = projs.get(k) if isinstance(projs.get(k), dict) else {}
        name = v.get("name") or p.get("name") or k
        todo = [t.get("text", "") for t in (v.get("todo") or {}).values() if isinstance(t, dict) and not t.get("done")]
        print(f"- {name} [{v.get('status','')}] 할 일 {len(todo)}개" + (f": {' / '.join(todo)[:150]}" if todo else ""))


def cmd_find(a):
    data = _get(a.path) or {}
    q = a.q.lower()
    hits = {k: v for k, v in (data.items() if isinstance(data, dict) else enumerate(data or []))
            if q in json.dumps(v, ensure_ascii=False).lower()}
    print(f"{len(hits)}건")
    _out(hits)


def main():
    ap = argparse.ArgumentParser(description="K&M 앱 데이터 읽기 (읽기 전용)")
    sp = ap.add_subparsers(dest="cmd")
    sp.add_parser("paths")
    k = sp.add_parser("keys"); k.add_argument("path")
    g = sp.add_parser("get"); g.add_argument("path"); g.add_argument("--last", type=int)
    f = sp.add_parser("find"); f.add_argument("path"); f.add_argument("q")
    l = sp.add_parser("logs"); l.add_argument("--from", dest="frm"); l.add_argument("--to"); l.add_argument("--who")
    s = sp.add_parser("sitelog"); s.add_argument("--days", type=int, default=7); s.add_argument("--site")
    sp.add_parser("board")
    a = ap.parse_args()
    if a.cmd in (None, "paths"):
        for app, m in PATHS.items():
            print(f"\n[{app}]")
            for p, d in m.items():
                print(f"  {p:<45} {d}")
    elif a.cmd == "keys":
        d = _get(a.path, shallow="true")
        print("\n".join(sorted(d)) if isinstance(d, dict) else d)
    elif a.cmd == "get":
        _out(_get(a.path, orderBy="$key", limitToLast=a.last) if a.last else _get(a.path))
    elif a.cmd == "find":
        cmd_find(a)
    elif a.cmd == "logs":
        cmd_logs(a)
    elif a.cmd == "sitelog":
        cmd_sitelog(a)
    elif a.cmd == "board":
        cmd_board(a)


if __name__ == "__main__":
    main()
