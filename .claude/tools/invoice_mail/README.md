# Invoice mail (accounts@)

Max issues an invoice in the app, then says e.g. "1659 보내줘". Claude:

1. Runs in a session NOT linked to Max's Mac (a Mac-linked session blocks oauth2/gmail.googleapis.com and cdn.jsdelivr.net).
2. `python3 .claude/tools/invoice_mail/invoice_draft.py INV-1659 [--to x] [--cc y]`
   - renders the invoice PDF (+ Subcontractor Statement when the builder has needsStatement/statementTemplate)
     with the real app code from this repo (pull main first) in headless Chromium,
     read-only (viewer role, Firebase writes blocked). JS libs come from ./libs (no CDN needed).
   - To = builder invoiceEmail (else email). Subject "Payment request DD/MM/YY K&M Tiling Bathurst" (Sydney date),
     body = the app's email template, accounts@ Gmail signature from settings.sendAs.
   - From shows as "Kathleen Lim <accounts@...>" (sendAs displayName is empty, so the name is a fallback).
   - prints draft_id, to, subject, attachments, pdf_dir, and already_sent (earlier sent mails carrying the same INV-xxxx.pdf).
     If already_sent is not empty, tell Max it was sent before offering to send again.
3. Show Max the draft summary (and the PDFs from pdf_dir if useful). Send ONLY after Max says OK:
   `python3 invoice_draft.py --send <draft_id>`

Builders in PORTALS (invoice_draft.py) also need a claim in another program (Baseline: Payapps + Work Comp; Akura, MaasDPC/Stanaway: Premier).
The output's `portal` field is set for them: tell Max up front, before showing or sending the draft. Add new ones to PORTALS.

Not handled: Work Comp package builders (needsWorkComp, e.g. Baseline) - app's 📦 패키지 PDF; do by hand for now.
The Statement date is the day it's generated (same as pressing 📄 Statement in the app that day).

No separate sent date: the invoice date (발행날짜) is the date it was sent (Max, 2026-10-21).

Per-site CC: Firebase `claudeMeta/invoiceMail/siteCc` ({match word: address}) adds a CC when the project name/address
matches (e.g. TWPZ Wildlife Resort -> MaasDPC site contact, Max 2026-10-26). Add new ones there, not in this public repo.

Company rename notice (Max 2026-11-26): while the invoice shows the new name (K&M Tiling Pty Ltd), the first mail to each
builder gets one extra line saying the name changed (RENAME_NOTICE). Output `rename_notice` says whether it is in.
Who got it is in Firebase `claudeMeta/renameNotice` (`notified` is recorded on --send; `pending` = drafts not sent yet),
shared by every Claude project. `--notice yes|no` forces it on/off for one draft.
