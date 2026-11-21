// 지식체계 HTML 점검: 콘솔 오류, 탭별 가로 넘침(1366·390), 클래스 지도 글자 넘침·겹침·라벨 겹침(클래스별 선택),
// 탐색기 이동·뒤로, 추적표 행 수, 인쇄. 사용: node scripts/check_knowledge_html.mjs <html> <스크린샷폴더>
import { createRequire } from "module";
import { pathToFileURL } from "url";
import path from "path";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const [file, outDir = "."] = process.argv.slice(2);
const url = pathToFileURL(path.resolve(file)).href;
const browser = await chromium.launch();
const R = { errors: [], checks: {} };
async function open(viewport) {
  const page = await browser.newPage({ viewport });
  page.on("console", (m) => { if (m.type() === "error") R.errors.push(`${viewport.width}: ${m.text()}`); });
  page.on("pageerror", (e) => R.errors.push(`${viewport.width}: ${e}`));
  await page.goto(url, { waitUntil: "load" });
  return page;
}
const ovf = (p) => p.evaluate(() => document.documentElement.scrollWidth - innerWidth);
const page = await open({ width: 1366, height: 768 });
R.checks.overflow = {};
for (const t of ["prog", "map", "exp", "trace"]) {
  await page.click(`#t-${t}`);
  R.checks.overflow[`1366_${t}`] = await ovf(page);
  await page.screenshot({ path: `${outDir}/kb_${t}_1366.png`, fullPage: t !== "trace" });
}
await page.click("#t-map");
R.checks.map = await page.evaluate(() => {
  const svg = document.querySelector("#mapwrap svg"), vb = svg.viewBox.baseVal, out = { textOverflow: [], overlap: [], outOfView: [] };
  const nodes = [...svg.querySelectorAll(".cnode")];
  const boxes = nodes.map((g) => ({ id: g.dataset.cls, b: g.querySelector(".box").getBBox() }));
  nodes.forEach((g, i) => {
    const b = boxes[i].b;
    for (const t of g.querySelectorAll("text")) { const tb = t.getBBox(); if (tb.x + tb.width > b.x + b.width - 6 || tb.y < b.y || tb.y + tb.height > b.y + b.height) out.textOverflow.push(boxes[i].id); }
    if (b.x < 0 || b.y < 0 || b.x + b.width > vb.width || b.y + b.height > vb.height) out.outOfView.push(boxes[i].id);
  });
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i].b, c = boxes[j].b; if (a.x < c.x + c.width && c.x < a.x + a.width && a.y < c.y + c.height && c.y < a.y + a.height) out.overlap.push(`${boxes[i].id}/${boxes[j].id}`);
  }
  const labelIssues = [];
  for (const g of nodes) {
    g.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    const labs = [...svg.querySelectorAll(".elabel rect")].map((r) => r.getBBox());
    let lo = 0, ln = 0, lv = 0;
    for (let i = 0; i < labs.length; i++) {
      const a = labs[i];
      for (let j = i + 1; j < labs.length; j++) { const c = labs[j]; if (a.x < c.x + c.width && c.x < a.x + a.width && a.y < c.y + c.height && c.y < a.y + a.height) lo++; }
      if (boxes.some(({ b }) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height)) ln++;
      if (a.x < 0 || a.y < 0 || a.x + a.width > vb.width || a.y + a.height > vb.height) lv++;
    }
    if (lo || ln || lv) labelIssues.push({ cls: g.dataset.cls, labels: labs.length, overlap: lo, onNode: ln, outOfView: lv });
  }
  out.labelIssues = labelIssues;
  return out;
});
await page.click('.cnode[data-cls="Defect"]');
await page.waitForTimeout(350);
await page.screenshot({ path: `${outDir}/kb_map_defect.png` });
await page.click("#toExp");
R.checks.filterAfterMap = await page.evaluate(() => document.getElementById("listTitle").textContent);
// 탐색기: D2 선택 → 관계 링크로 이동 → 뒤로
await page.click('#clschips button[data-c=""]');
await page.fill("#q", "D2");
await page.click('#elist [data-pick="D2"]');
R.checks.d2Relations = await page.evaluate(() => document.querySelectorAll("#detail .lnk").length);
await page.screenshot({ path: `${outDir}/kb_exp_d2.png` });
await page.click('#detail .lnk[data-go="K03"]');
R.checks.navigated = await page.evaluate(() => document.querySelector("#detail h2").textContent);
await page.click("#backBtn");
R.checks.back = await page.evaluate(() => document.querySelector("#detail h2").textContent);
await page.click("#t-trace");
R.checks.traceRows = await page.evaluate(() => ["tr1", "tr2", "tr3", "tr4", "tr5"].map((id) => document.querySelectorAll(`#${id} tbody tr`).length));
await page.emulateMedia({ media: "print" });
await page.screenshot({ path: `${outDir}/kb_print.png`, fullPage: true });
const m = await open({ width: 390, height: 844 });
for (const t of ["prog", "map", "exp", "trace"]) { await m.click(`#t-${t}`); R.checks.overflow[`390_${t}`] = await ovf(m); }
await m.click("#t-prog");
await m.screenshot({ path: `${outDir}/kb_prog_390.png`, fullPage: true });
await browser.close();
console.log(JSON.stringify(R, null, 1));
const c = R.checks;
const bad = R.errors.length || Object.values(c.overflow).some((v) => v > 0) || c.map.textOverflow.length || c.map.overlap.length ||
  c.map.outOfView.length || c.map.labelIssues.length || c.navigated === c.back || c.d2Relations < 5;
process.exit(bad ? 1 : 0);
