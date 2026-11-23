#!/usr/bin/env python3
"""월말 청구 마감 알림 재료 — 읽기 전용. 개발·조회 프로젝트 공용.

빌더 설정(invoiceBuilders.claimDay)의 청구일과 최근 진행(PROGRESS) 인보이스를 보고,
오늘이 알림 날인지와 이번 마감에 청구할 빌더·현장 목록을 JSON으로 출력합니다.

  claim_deadlines.py                 오늘(시드니) 기준. 알림 날이 아니면 {"remind": false}
  claim_deadlines.py --date 2026-11-20   그 날짜 기준으로 계산 (확인용)
  claim_deadlines.py --force         알림 날이 아니어도 이번 달 마감 목록 출력

알림 날 규칙 (Kathleen 2026-11-17 요청: 마감 3~4일 전):
  - 25일 마감  → 21일
  - 말일 마감  → 말일 3일 전
  - 그날이 토·일이면 그 앞 금요일
  - 청구일이 정해져 있지 않은데 진행 청구 중인 빌더는 말일 알림에 같이 넣음
"""
import argparse, calendar, json, os, sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_data as ad  # noqa: E402  (같은 인증 재사용)

ACTIVE_DAYS = 90  # 이 기간 안에 PROGRESS 인보이스가 있으면 진행 중으로 봄


def _friday_if_weekend(d):
    while d.weekday() >= 5:  # 토=5, 일=6
        d -= timedelta(days=1)
    return d


def deadlines_for_month(y, m):
    last = calendar.monthrange(y, m)[1]
    d25 = date(y, m, 25)
    deom = date(y, m, last)
    return {
        "25": {"deadline": d25, "remind_on": _friday_if_weekend(d25 - timedelta(days=4))},
        "EOM": {"deadline": deom, "remind_on": _friday_if_weekend(deom - timedelta(days=3))},
    }


def build(today, force=False):
    dl = deadlines_for_month(today.year, today.month)
    due = [k for k, v in dl.items() if v["remind_on"] == today]
    if not due and not force:
        nxt = sorted(v["remind_on"] for v in dl.values() if v["remind_on"] > today)
        return {"remind": False, "today": today.isoformat(),
                "next_remind_on": nxt[0].isoformat() if nxt else None}
    if force and not due:
        due = list(dl.keys())

    builders = ad._get("invoiceBuilders") or {}
    invoices = ad._get("invoices") or {}
    since = (today - timedelta(days=ACTIVE_DAYS)).isoformat()
    # 현황판 돈 메모(관리자만): 인보이스 번호로 현장과 연결해서 다음 청구 때 챙길 것을 같이 보여 준다
    money_note = {}
    for m in (ad._get("siteBoardMoney") or {}).values():
        if isinstance(m, dict) and (m.get("note") or "").strip():
            for n in m.get("invoiceNums") or []:
                money_note[n] = m["note"].strip()

    by_builder = {}
    for inv in invoices.values():
        if not isinstance(inv, dict) or inv.get("type") != "PROGRESS":
            continue
        if (inv.get("invoiceDate") or "") < since or inv.get("status") in ("DRAFT", "NO_PAYMENT"):
            continue
        b = by_builder.setdefault(inv.get("builderName") or "?", {})
        site = (inv.get("address") or "").strip() or "(주소 없음)"
        prev = b.get(site)
        if not prev or (inv.get("invoiceDate") or "") > prev["last_date"]:
            b[site] = {"site": site, "last_inv": inv.get("invoiceNum"),
                       "last_date": inv.get("invoiceDate"), "last_status": inv.get("status"),
                       "board_money_note": money_note.get(inv.get("invoiceNum"))}

    groups = {k: [] for k in due}
    for bid, b in builders.items():
        if not isinstance(b, dict):
            continue
        name = b.get("name") or bid
        cd = str(b.get("claimDay") or "").strip().upper()
        key = "25" if cd == "25" else ("EOM" if cd == "EOM" else None)
        sites = sorted(by_builder.get(name, {}).values(), key=lambda s: s["last_date"] or "", reverse=True)
        if key is None:
            if not sites:
                continue
            key = "EOM"  # 날짜 없는 진행 청구 빌더는 말일 알림에
            fixed = False
        else:
            fixed = True
        if key not in groups:
            continue
        groups[key].append({
            "builder": name, "claimDay": cd or None, "fixed_date": fixed,
            "payTerm": b.get("payTerm"), "contractNote": b.get("contractNote"),
            "active": bool(sites), "sites": sites,
        })
    for g in groups.values():
        g.sort(key=lambda x: (not x["active"], not x["fixed_date"], x["builder"].lower()))

    return {
        "remind": True, "today": today.isoformat(),
        "deadlines": [{"kind": k, "deadline": dl[k]["deadline"].isoformat(),
                       "weekday": "월화수목금토일"[dl[k]["deadline"].weekday()],
                       "builders": groups[k]} for k in due],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date")
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    today = date.fromisoformat(a.date) if a.date else datetime.now(ZoneInfo("Australia/Sydney")).date()
    print(json.dumps(build(today, a.force), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
