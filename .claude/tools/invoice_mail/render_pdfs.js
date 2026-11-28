// Render an invoice's PDF (+ Subcontractor Statement if the builder needs one) using the
// real invoice app code in headless Chromium, read-only (viewer role, no Firebase writes).
// usage: node render_pdfs.js <repoDir> <libsDir> <INV-number> <outDir>
const http = require('http'), fs = require('fs'), path = require('path');
const { chromium } = require('/opt/node-tools/node_modules/playwright');
const [repo, libs, invNum, out] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const LIBS = { 'pdf-lib@1.17.1': 'pdf-lib.min.js', 'html2canvas@1.4.1': 'html2canvas.min.js', 'jspdf@2.5.1': 'jspdf.umd.min.js' };
const srv = http.createServer((req, res) => {
  const p = decodeURIComponent(req.url.split('?')[0]).replace(/^\/worklog\//, '/');
  let f = path.join(repo, p); if (f.endsWith('/')) f += 'index.html';
  if (!f.startsWith(repo) || !fs.existsSync(f)) { res.statusCode = 404; return res.end(); }
  res.setHeader('Content-Type', f.endsWith('.pdf') ? 'application/pdf' : f.endsWith('.html') ? 'text/html; charset=utf-8' : 'application/octet-stream');
  fs.createReadStream(f).pipe(res);
}).listen(0, async () => {
  const port = srv.address().port;
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 1280, height: 900 } });
  await ctx.route('**/*', r => {
    const u = r.request().url();
    const m = u.match(/cdn\.jsdelivr\.net\/npm\/([^/]+)\//);
    if (m && LIBS[m[1]]) return r.fulfill({ path: path.join(libs, LIBS[m[1]]), contentType: 'application/javascript' });
    if (u.startsWith('http://127.0.0.1') || u.includes('firebaseio.com')) {
      if (r.request().method() !== 'GET') return r.abort();   // never write to Firebase
      // 앱이 붙인 ?auth= 대신 서비스 계정 토큰(FB_ACCESS_TOKEN)으로 읽기 → DB 규칙이 잠겨도 동작
      if (u.includes('firebaseio.com') && process.env.FB_ACCESS_TOKEN) {
        const x = new URL(u); x.searchParams.delete('auth'); x.searchParams.set('access_token', process.env.FB_ACCESS_TOKEN);
        return r.continue({ url: x.toString() });
      }
      return r.continue();
    }
    return r.abort();
  });
  await ctx.addInitScript(() => {
    sessionStorage.setItem('invoice_unlocked', 'true'); sessionStorage.setItem('invoice_user_id', 'claude');
    sessionStorage.setItem('invoice_user_role', 'viewer'); sessionStorage.setItem('invoice_user_name', 'Claude');
    // 앱의 Firebase 로그인 확인 통과용 (실제 토큰은 위 route 에서 서비스 계정 토큰으로 바꿔 붙임)
    localStorage.setItem('knm_fb_auth_v2', JSON.stringify({ id: 'claude', uid: 'claude', admin: false, idToken: 'x', refreshToken: 'x', exp: 4102444800000 }));
  });
  const page = await ctx.newPage();
  page.on('dialog', d => d.accept());
  await page.goto(`http://127.0.0.1:${port}/worklog/invoice/`);
  await page.waitForFunction(() => typeof invoices !== 'undefined' && invoices.length > 0, null, { timeout: 60000 });
  const info = await page.evaluate(n => {
    const inv = invoices.find(i => i.invoiceNum === n);
    if (!inv) return null;
    const b = builders.find(x => x.name === inv.builderName) || {};
    const co = companies.find(c => c.id === inv.companyId) || companies[0] || {};
    return { id: inv.id, invoiceNum: inv.invoiceNum, builderName: inv.builderName, status: inv.status, amount: inv.amount,
      projectName: inv.projectName || '', address: inv.address || '', to: b.invoiceEmail || b.email || inv.privateEmail || '',
      needsStatement: !!(b.needsStatement || b.statementTemplate), needsWorkComp: !!b.needsWorkComp,
      companyName: (typeof invCoName === 'function' ? invCoName(co, inv) : co.name) || '', companyEmail: co.contactEmail || co.email || '' };
  }, invNum);
  if (!info) { console.log(JSON.stringify({ error: 'invoice not found: ' + invNum })); process.exit(2); }
  const files = [];
  const grab = async (fn) => {
    const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 90000 }), page.evaluate(fn, info.id)]);
    const f = path.join(out, dl.suggestedFilename()); await dl.saveAs(f); files.push(f);
  };
  await page.evaluate(id => printInvoice(id), info.id);
  await page.waitForTimeout(1500);
  await grab(() => downloadInvoicePDF(null));
  if (info.needsStatement) await grab(id => openSubcontractorStatement(id));
  console.log(JSON.stringify({ ...info, files }, null, 1));
  await browser.close(); srv.close();
});
