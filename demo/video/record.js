// Records the Veilgate demo video: drives the real dashboard in headless Chrome, scene by scene, with captions.
//
//   npm i puppeteer-core            (needs ffmpeg and Google Chrome on the machine)
//   BASE=http://localhost:8091 RUN_LOG=real_run.txt node demo/video/record.js
//
// Output (demo/video/out/): veilgate-demo.mp4 (captions burned in), veilgate-demo-clean.mp4 (no captions, for voice-over),
// veilgate-demo.srt (caption timings), voiceover-script.txt.
// The terminal scene replays the REAL output of `python -m demo.clinic_demo` saved in RUN_LOG.

const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const puppeteer = require("puppeteer-core");

const BASE = process.env.BASE || "http://localhost:8091";
const RUN_LOG = process.env.RUN_LOG || "real_run.txt";
const CAPTIONS = process.env.CAPTIONS !== "0";
const OUT = path.join(__dirname, "out", CAPTIONS ? "captioned" : "clean");
fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const FONT = `<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap">`;

// ---------------------------------------------------------------------------------------------------------------
// overlay: caption, chapter tag, requirement chip, fake cursor
// ---------------------------------------------------------------------------------------------------------------
const overlay = (captions) => {
  if (document.getElementById("vo")) return;
  const st = document.createElement("style");
  st.textContent = `
    #vo{position:fixed;inset:0;pointer-events:none;z-index:99999;font-family:Outfit,system-ui,sans-serif}
    #vo-cap{position:absolute;left:50%;bottom:34px;transform:translateX(-50%);max-width:1080px;background:rgba(15,23,42,.9);color:#fff;font-weight:600;font-size:25px;line-height:1.35;padding:13px 26px;border-radius:14px;text-align:center;opacity:0;transition:opacity .3s;box-shadow:0 12px 30px -10px rgba(0,0,0,.45)}
    #vo-tag{position:absolute;left:50%;top:14px;transform:translateX(-50%);background:#fff;border:1px solid #c7d2fe;color:#4338ca;font-weight:700;font-size:15px;padding:6px 16px;border-radius:999px;opacity:0;transition:opacity .3s;box-shadow:0 6px 16px -8px rgba(30,41,99,.4)}
    #vo-chip{position:absolute;right:18px;top:14px;background:linear-gradient(135deg,#4f46e5,#0ea5e9 60%,#14b8a6);color:#fff;font-weight:600;font-size:13.5px;padding:7px 15px;border-radius:999px;box-shadow:0 8px 18px -8px rgba(79,70,229,.7)}
    #vo-cur{position:absolute;left:700px;top:420px;width:26px;height:26px;transition:left .75s cubic-bezier(.4,0,.2,1),top .75s cubic-bezier(.4,0,.2,1);filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}
    .vo-rip{position:absolute;width:14px;height:14px;margin:-7px;border-radius:50%;border:3px solid #4f46e5;animation:rip .6s ease-out forwards}
    @keyframes rip{to{transform:scale(3.4);opacity:0}}`;
  document.head.append(st);
  const o = document.createElement("div");
  o.id = "vo";
  o.innerHTML = `${captions ? '<div id="vo-cap"></div><div id="vo-tag"></div>' : ""}<div id="vo-chip">Runs on Nebius Token Factory · NVIDIA Nemotron</div>
    <svg id="vo-cur" viewBox="0 0 24 24"><path d="M3 2l7.5 19 2.7-7.8L21 10.5z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  document.body.append(o);
};

// ---------------------------------------------------------------------------------------------------------------
async function main() {
  const browser = await puppeteer.launch({ executablePath: "/usr/bin/google-chrome", headless: "new", args: ["--no-sandbox", "--hide-scrollbars", "--window-size=1440,900"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });

  const segments = []; // {file, caps:[{t,text}]}
  let cur = null;
  const now = () => (Date.now() - cur.start) / 1000;

  async function ready() { await page.evaluate(overlay, CAPTIONS); }
  async function cap(text) {
    if (!CAPTIONS || !text) return;
    cur.caps.push({ t: now(), text });
    await page.evaluate((t) => { const c = document.getElementById("vo-cap"); if (!c) return; c.style.opacity = 0; setTimeout(() => { c.textContent = t; c.style.opacity = 1; }, 200); }, text);
  }
  async function tag(text) { if (CAPTIONS) await page.evaluate((t) => { const c = document.getElementById("vo-tag"); if (c) { c.textContent = t; c.style.opacity = t ? 1 : 0; } }, text); }
  async function hush() { if (CAPTIONS) await page.evaluate(() => { const c = document.getElementById("vo-cap"); if (c) c.style.opacity = 0; }); }

  async function centerOf(el) { const b = await el.boundingBox(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; }
  async function glide(x, y) {
    await page.evaluate((x, y) => { const c = document.getElementById("vo-cur"); if (c) { c.style.left = x + "px"; c.style.top = y + "px"; } }, x, y);
    await sleep(800);
  }
  async function click(el) {
    const { x, y } = await centerOf(el);
    await glide(x, y);
    await page.evaluate((x, y) => { const r = document.createElement("div"); r.className = "vo-rip"; r.style.left = x + "px"; r.style.top = y + "px"; document.getElementById("vo").append(r); setTimeout(() => r.remove(), 700); }, x, y);
    await page.mouse.click(x, y);
  }
  const byText = async (sel, text) => (await page.evaluateHandle((sel, text) => [...document.querySelectorAll(sel)].find((e) => e.textContent.trim().startsWith(text)) || null, sel, text)).asElement();
  async function clickText(sel, text) { const el = await byText(sel, text); if (!el) throw new Error(`no ${sel} starting with "${text}"`); await click(el); }
  async function go(url) { await page.goto(url, { waitUntil: "networkidle2", timeout: 30000 }); await ready(); await sleep(500); }
  async function hash(h) { await page.evaluate((h) => (location.hash = h), h); await sleep(1100); }

  async function scene(name, seconds, fn) {
    const file = path.join(OUT, `${String(segments.length).padStart(2, "0")}-${name}.webm`);
    cur = { start: 0, caps: [] };
    const rec = await page.screencast({ path: file });
    cur.start = Date.now();
    try { await fn(); } finally {
      const spent = (Date.now() - cur.start) / 1000;
      if (spent < seconds) await sleep((seconds - spent) * 1000);
      await rec.stop();
    }
    console.log(`scene ${name}: ${((Date.now() - cur.start) / 1000).toFixed(1)}s (target ${seconds}s)`);
    segments.push({ file, caps: cur.caps });
  }

  // ---------- pages built from files
  const logLines = fs.readFileSync(RUN_LOG, "utf8").split("\n");
  const header = logLines.find((l) => l.startsWith("story=")) || "";
  const model = (header.match(/model=(\S+)/) || [, "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"])[1];
  const clip = (s, n = 150) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
  let term = logLines.filter((l) => /^ {2}\[(orchestrator|data_agent|reporter)\]/.test(l)).map((l) => clip(l.trim()));
  const fi = logLines.findIndex((l) => l.startsWith("FINAL ANSWER TO USER"));
  const finalAns = logLines.slice(fi, fi + 12).filter((l) => l.trim()).slice(0, 4).map((l) => clip(l.trim(), 130));
  term = [...term, ...finalAns];
  const INTERVAL = 1.15;
  const termHtml = `<!doctype html><meta charset=utf-8>${FONT}<style>
    body{margin:0;height:100vh;background:linear-gradient(135deg,#eef2ff,#ecfeff);display:grid;place-items:center;font-family:Outfit,sans-serif}
    .win{width:1280px;border-radius:16px;background:#0b1020;box-shadow:0 40px 80px -30px rgba(30,41,99,.55);overflow:hidden}
    .bar{height:42px;background:#151b33;display:flex;align-items:center;gap:8px;padding:0 16px;color:#94a3b8;font:500 14px Outfit}
    .bar i{width:12px;height:12px;border-radius:50%;display:inline-block}
    pre{margin:0;padding:22px 26px;height:640px;overflow:hidden;font:600 17px/1.62 "JetBrains Mono",monospace;color:#cbd5e1;white-space:pre-wrap;word-break:break-word}
    .l{opacity:0;transition:opacity .35s}.l.on{opacity:1}
    .p{color:#a5b4fc}.tok{color:#a5b4fc;background:rgba(99,102,241,.2);border-radius:4px;padding:0 3px}
    .bad{color:#fca5a5;font-weight:700}.ok{color:#86efac}.dim{color:#64748b}.ag{color:#67e8f9}
  </style><div class="win"><div class="bar"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i><span style="margin-left:10px">~/hackt/veilgate — python -m demo.clinic_demo</span></div><pre id="t"></pre></div>
  <script>
    const LINES=${JSON.stringify(term)}, MODEL=${JSON.stringify(model)}, IV=${INTERVAL * 1000};
    const t=document.getElementById('t');
    const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
    const fmt=s=>esc(s).replace(/(tok_[a-z_]+_[0-9a-f]{12})/g,'<span class="tok">$1</span>').replace(/\\b(DENIED|blocked)\\b/g,'<span class="bad">$1</span>').replace(/^\\[(\\w+)\\]/,'<span class="ag">[$1]</span>');
    const add=(h,c='')=>{const d=document.createElement('div');d.className='l '+c;d.innerHTML=h;t.append(d);requestAnimationFrame(()=>d.classList.add('on'));};
    window.play=()=>{add('<span class="p">$</span> python -m demo.clinic_demo --story attack');
      setTimeout(()=>add('<span class="dim">model = </span><span class="ok">'+esc(MODEL)+'</span><span class="dim">  (NVIDIA Nemotron on Nebius Token Factory)</span>'),700);
      LINES.forEach((l,i)=>setTimeout(()=>add(fmt(l.replace(/^\\s+/,''))),1800+i*IV));};
  </script>`;
  fs.writeFileSync(path.join(OUT, "terminal.html"), termHtml);
  const idx = (re) => Math.max(0, term.findIndex((l) => re.test(l)));
  const tAt = (i) => 1.8 + i * INTERVAL;

  const card = (body) => `<!doctype html><meta charset=utf-8>${FONT}<style>
    body{margin:0;height:100vh;display:grid;place-items:center;font-family:Outfit,sans-serif;color:#0f172a;
      background:radial-gradient(60% 55% at 50% 0%,rgba(99,102,241,.16),transparent 70%),radial-gradient(35% 40% at 92% 35%,rgba(20,184,166,.14),transparent 70%),radial-gradient(circle at 1px 1px,#e8ebf7 1px,transparent 0) 0 0/26px 26px,#fff}
    .w{text-align:center;max-width:1180px}.logo{width:76px;height:76px;margin:0 auto 18px}
    h1{font-size:92px;line-height:1;margin:0 0 14px;letter-spacing:-3px;font-weight:800}.g{background:linear-gradient(135deg,#4f46e5,#0ea5e9 60%,#14b8a6);-webkit-background-clip:text;background-clip:text;color:transparent}
    p{font-size:30px;color:#475569;margin:0 0 30px}.row{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;margin-top:12px}
    .c{padding:12px 22px;border-radius:999px;background:#fff;border:1px solid #dfe3f1;font-weight:600;font-size:21px;box-shadow:0 10px 24px -14px rgba(30,41,99,.4)}
    .c b{color:#15803d;margin-right:8px}.f{font-size:19px;color:#64748b;margin-top:22px}h2{font-size:40px;margin:0 0 22px;letter-spacing:-1px}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px 14px;text-align:left;margin:0 auto;max-width:1000px}.grid .c{font-size:21px}
  </style><div class="w">${body}</div>`;
  fs.writeFileSync(path.join(OUT, "title.html"), card(`
    <svg class="logo" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#4f46e5"/><path d="M16 6l8 3v7c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V9z" fill="none" stroke="#fff" stroke-width="2"/></svg>
    <h1><span class="g">Veilgate</span></h1><p>Governance for AI agents: private by default, every hop traced.</p>
    <div class="row"><span class="c">Track: Best Apps and Agents</span><span class="c">Runs on Nebius Token Factory</span><span class="c">NVIDIA Nemotron Nano · Super · Ultra</span><span class="c">Open source · MIT</span></div>`));
  fs.writeFileSync(path.join(OUT, "end.html"), card(`
    <h2><span class="g">What you just saw</span></h2><div class="grid">
    <span class="c"><b>✓</b>Runs on Nebius Token Factory (live runtime calls)</span><span class="c"><b>✓</b>NVIDIA Nemotron: Nano · Super · Ultra</span>
    <span class="c"><b>✓</b>Sensitive data → vault tokens (30+ identifier types)</span><span class="c"><b>✓</b>Earned authority scores + tool gate</span>
    <span class="c"><b>✓</b>Prompt-injection shield + Nemotron privacy judge</span><span class="c"><b>✓</b>Full tracing: Flow · Sequence · Timeline</span>
    <span class="c"><b>✓</b>Tamper-evident hash-chained receipts</span><span class="c"><b>✓</b>Dashboard: Overview · Trust · Users · Policies · Test</span>
    <span class="c"><b>✓</b>LangGraph / LangChain / any framework (5 calls)</span><span class="c"><b>✓</b>Open source (MIT) · README · one-command Docker</span></div>
    <div class="f">Track: Best Apps and Agents · Nebius × NVIDIA Global AI Hackathon</div>`));

  // ---------- the scenes
  await scene("title", 6, async () => { await go("file://" + path.join(OUT, "title.html")); await sleep(300); });

  await scene("landing", 38, async () => {
    await go(`${BASE}/app/`);
    await tag("1 · The problem");
    await cap("AI agents read records, call tools and send email. Nobody can see what they did.");
    await sleep(6500);
    await tag("2 · Live detection");
    await clickText("a, button", "Try it live"); await sleep(1500);
    await cap("Live: names, IDs and dates become vault tokens before any model sees them.");
    await sleep(3500);
    const ta = await page.$("#demo textarea");
    await cap("Edit the text: detection updates instantly.");
    await click(ta);
    await page.keyboard.press("End");
    await page.keyboard.type("  Email jane.doe@mail.com, card 4111 1111 1111 1111.", { delay: 38 });
    await sleep(2200);
    await clickText(".seg button", "India KYC");
    await cap("India DPDP identifiers too: Aadhaar, PAN, UPI, salary.");
    await sleep(3800);
    await clickText(".seg button", "Agent attack");
    await cap("A poisoned tool result is blocked before the agent reads it (authority −30).");
    await sleep(4500);
    await tag("3 · Sign in");
    await cap("Sign in to the dashboard.");
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" })); await sleep(900);
    await clickText("a", "Sign in"); await sleep(1200);
    await clickText(".demo button", "Admin"); await sleep(500);
    await clickText("button", "Sign in"); await sleep(1800);
  });

  await scene("terminal", 30, async () => {
    await go("file://" + path.join(OUT, "terminal.html"));
    await tag("4 · Real agents on NVIDIA Nemotron");
    await page.evaluate(() => window.play());
    await cap("Three real agents on NVIDIA Nemotron via Nebius Token Factory.");
    const bi = idx(/blocked/), di = idx(/DENIED/);
    await sleep(Math.max(0, tAt(1) * 1000));
    await cap("The model only ever sees tokens, never the patient's data.");
    await sleep(Math.max(0, (tAt(bi) - tAt(1)) * 1000));
    await cap("Poisoned search result: blocked before the agent reads it.");
    await sleep(Math.max(0, (tAt(di) - tAt(bi)) * 1000));
    await cap("Outside email and a tool it was never given: denied.");
    await sleep(Math.max(0, (tAt(term.length - 3) - tAt(di)) * 1000));
    await cap("The task still completes, and the answer holds no real identifiers.");
  });

  // featured trace: the newest flagged session for dr.iyer
  await go(`${BASE}/app/#/overview`);
  // the on-camera sign-in can race; make sure the session is real before the dashboard scenes
  const signedIn = await page.evaluate(async () => (await fetch("/api/auth/me")).ok);
  if (!signedIn) {
    await page.evaluate(() => fetch("/api/auth/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: "admin@veilgate.demo", password: "admin-demo-2026" }) }));
    await go(`${BASE}/app/#/overview`);
  }
  const traceId = await page.evaluate(async () => { const t = await (await fetch("/api/traces?limit=50")).json(); return (t.find((x) => x.user_name === "dr.iyer" && x.status === "flagged") || t[0]).id; });

  await scene("trace", 36, async () => {
    await go(`${BASE}/app/#/traces/${traceId}`);
    await tag("5 · Full tracing");
    await cap("Every run is one trace: user → agent → agent → model → tool, with a decision on every hop.");
    await sleep(7500);
    const node = await page.evaluateHandle(() => [...document.querySelectorAll("svg g")].find((g) => g.textContent.includes("web_search") && g.querySelector("rect")));
    await cap("Click any hop to see what was protected, and why it was blocked.");
    await click(node.asElement()); await sleep(5500);
    const item = await byText(".span-item", "data_agent"); if (item) { await click(item); await sleep(4000); }
    await clickText(".tabs button", "Sequence");
    await cap("The same story, step by step. Red means denied or blocked.");
    await sleep(3500);
    await page.evaluate(() => window.scrollTo({ top: 420, behavior: "smooth" })); await sleep(4000);
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" })); await sleep(1200);
  });

  await scene("scores", 17, async () => {
    await tag("6 · Earned authority");
    await clickText(".tabs button", "Agents & scores");
    await cap("Authority is earned: violations cost points, gates stop risky tools, sub-agents are capped by their parent.");
    await sleep(8000);
    await page.evaluate(() => window.scrollTo({ top: 330, behavior: "smooth" })); await sleep(5500);
  });

  await scene("receipts", 10, async () => {
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" })); await sleep(700);
    await tag("7 · Tamper-evident receipts");
    await clickText(".tabs button", "Receipts");
    await cap("Every decision is a hash-chained receipt. Verification: chain intact.");
    await sleep(4500);
  });

  await scene("montage", 18, async () => {
    const stops = [["overview", "Overview", "Needs attention: the latest violations, with who, what and why."], ["trust", "Trust & Tokens", "Trust & Tokens: a rating per user, tokens and violations over time."],
      ["users", "Users", "Users: who runs your agents, and how well-behaved they are."], ["test", "Test detection", "Test detection: try any text, even with hidden values."], ["policies", "Policies", "Policies: every rule and number lives in one config file."]];
    await tag("8 · And more");
    for (const [h, , text] of stops) {
      await cap(text); await hash(`#/${h}`);   // caption first, so it never sits on the previous page
      if (h === "test") { await clickText(".btn", "Hidden values"); await sleep(1600); }
      await sleep(h === "test" ? 1500 : 2200);
    }
  });

  await scene("end", 12, async () => { await go("file://" + path.join(OUT, "end.html")); await sleep(300); });

  await browser.close();

  // ---------- assemble
  // webm from the screen recorder carries no duration header, so read it from a full decode
  const durationOf = (f) => { const r = require("child_process").spawnSync("ffmpeg", ["-i", f, "-f", "null", "-"], { encoding: "utf8" }); const m = [...r.stderr.matchAll(/time=(\d+):(\d+):([\d.]+)/g)].pop(); return +m[1] * 3600 + +m[2] * 60 + +m[3]; };
  const lengths = segments.map((s) => durationOf(s.file));
  fs.writeFileSync(path.join(OUT, "segments.json"), JSON.stringify(segments.map((s, i) => ({ ...s, seconds: lengths[i] })), null, 1));
  const list = path.join(OUT, "list.txt");
  fs.writeFileSync(list, segments.map((s) => `file '${s.file}'`).join("\n"));
  const mp4 = path.join(__dirname, "out", CAPTIONS ? "veilgate-demo.mp4" : "veilgate-demo-clean.mp4");
  execFileSync("ffmpeg", ["-y", "-f", "concat", "-safe", "0", "-i", list, "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-movflags", "+faststart", mp4], { stdio: "ignore" });
  const total = lengths.reduce((a, b) => a + b, 0);
  console.log(`\nvideo: ${mp4}\nlength: ${Math.floor(total / 60)}:${String(Math.round(total % 60)).padStart(2, "0")}`);

  if (CAPTIONS) {
    const ts = (t) => { const ms = Math.round(t * 1000), z = (n, w = 2) => String(n).padStart(w, "0"); return `${z(Math.floor(ms / 3600000))}:${z(Math.floor(ms / 60000) % 60)}:${z(Math.floor(ms / 1000) % 60)},${z(ms % 1000, 3)}`; };
    let off = 0, n = 1, srt = "", vo = "";
    segments.forEach((seg, si) => {
      seg.caps.forEach((c, i) => {
        const end = i + 1 < seg.caps.length ? seg.caps[i + 1].t : lengths[si] - 0.3;
        srt += `${n++}\n${ts(off + c.t)} --> ${ts(off + Math.max(c.t + 1, end))}\n${c.text}\n\n`;
        vo += `[${Math.floor((off + c.t) / 60)}:${String(Math.floor((off + c.t) % 60)).padStart(2, "0")}] ${c.text}\n`;
      });
      off += lengths[si];
    });
    fs.writeFileSync(path.join(__dirname, "out", "veilgate-demo.srt"), srt);
    fs.writeFileSync(path.join(__dirname, "out", "voiceover-script.txt"), vo);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
