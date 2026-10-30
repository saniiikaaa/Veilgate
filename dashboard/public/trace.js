// The trace views: Flow (graph), Sequence (swimlanes), Timeline (list), Receipts.
import { h, s, pill, chip, when, num, scoreKind, scoreBar, tokenText, outcomePill, api } from "./ui.js";

const KIND = {
  user_to_agent: { color: "#4f46e5", label: "user → agent" },
  agent_to_user: { color: "#4f46e5", label: "agent → user" },
  agent_to_agent: { color: "#7c3aed", label: "agent ↔ agent" },
  agent_to_model: { color: "#0f766e", label: "agent → model" },
  model_to_agent: { color: "#0f766e", label: "model → agent" },
  agent_to_tool: { color: "#d97706", label: "agent → tool" },
  tool_to_agent: { color: "#d97706", label: "tool → agent" },
};
const BAD = "#dc2626";
const flagged = (sp) => sp.outcome === "denied" || sp.outcome === "blocked";
const nameOf = (id) => id.split(":").slice(1).join(":");
const typeOf = (id) => id.split(":")[0];

const STEP = {
  user_input: "prompt", handoff: "delegate", handoff_return: "reply", model_input: "ask model", model_output: "answer",
  tool_input: "call", tool_output: "result", user_output: "final answer",
};
const stepLabel = (sp) => (sp.tool && (sp.boundary === "tool_input" || sp.boundary === "tool_output") ? `${STEP[sp.boundary]} ${sp.tool}` : STEP[sp.boundary] || sp.boundary);

// ---------------------------------------------------------------------------------------------------------------
// detail of one span
// ---------------------------------------------------------------------------------------------------------------
function spanDetail(sp) {
  const kv = [];
  const add = (k, v) => v != null && v !== "" && kv.push(h("span", {}, k), h("span", {}, v));
  add("Agent", sp.agent);
  add("Step", stepLabel(sp));
  add("Reason", sp.reason);
  add("Latency", sp.latency_ms ? `${sp.latency_ms} ms` : null);
  add("Model", sp.model_latency_ms != null ? `${sp.model_latency_ms} ms · ${num(sp.tokens)} tokens` : null);
  if (sp.injection) add("Injection", sp.injection.join(" · "));
  return h("div", {},
    h("div", { class: "row", style: "flex-wrap:wrap;gap:6px" }, outcomePill(sp.outcome), pill(KIND[sp.kind]?.label || sp.kind, "mute")),
    h("div", { class: "kv" }, kv),
    sp.entities.length ? h("div", {}, h("div", { class: "muted", style: "font-size:12px;margin-top:6px" }, "Sensitive values replaced with tokens"), sp.entities.map((t) => chip(t))) : null,
    sp.text ? h("div", {}, h("div", { class: "muted", style: "font-size:12px;margin-top:6px" }, "What the receiver saw"), tokenText(sp.text)) : null,
    sp.score_changes.length ? h("div", {}, sp.score_changes.map((c) => h("div", {}, h("span", { class: `delta ${c.delta < 0 ? "neg" : "pos"}` }, `${c.delta > 0 ? "+" : ""}${c.delta}`), ` ${c.rule.replaceAll("_", " ")}`, c.reason ? h("span", { class: "muted" }, ` — ${c.reason}`) : null))) : null);
}

function spanItem(sp, selected, onClick) {
  return h("div", { class: `span-item ${selected ? "sel" : ""}`, onclick: onClick },
    h("div", { class: "top" }, h("b", {}, sp.agent), h("span", { class: "muted" }, `${stepLabel(sp)} · ${nameOf(sp.from)} → ${nameOf(sp.to)}`), outcomePill(sp.outcome),
      sp.score_changes.map((c) => h("span", { class: `delta ${c.delta < 0 ? "neg" : "pos"}` }, `${c.delta > 0 ? "+" : ""}${c.delta}`))),
    selected ? spanDetail(sp) : null);
}

// ---------------------------------------------------------------------------------------------------------------
// Flow graph
// ---------------------------------------------------------------------------------------------------------------
function layout(trace) {
  const agents = trace.nodes.filter((n) => n.type === "agent");
  const depth = (n) => { let d = 0, p = n.parent; while (p && d < 8) { d++; p = agents.find((a) => a.label === p)?.parent; } return d; };
  const maxD = Math.max(0, ...agents.map(depth));
  const W = 180, H = 62, X_USER = 24, X_AGENT = 215, IND = 50;
  const X_RIGHT = X_AGENT + maxD * IND + W + 150;
  const pos = {};
  agents.forEach((a, i) => { pos[a.id] = { x: X_AGENT + depth(a) * IND, y: 40 + i * 96, w: W, h: H }; });
  trace.nodes.filter((n) => n.type === "user").forEach((u, i) => { pos[u.id] = { x: X_USER, y: (agents.length ? pos[agents[0].id].y : 40) + i * 96, w: 140, h: H }; });

  const right = trace.nodes.filter((n) => n.type === "model" || n.type === "tool");
  const want = (n) => {
    const ys = trace.edges.filter((e) => e.from === n.id || e.to === n.id).map((e) => pos[e.from === n.id ? e.to : e.from]).filter(Boolean).map((p) => p.y + p.h / 2);
    return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length - 26 : 40;
  };
  right.sort((a, b) => want(a) - want(b));
  let last = -Infinity;
  right.forEach((n) => { const y = Math.max(want(n), last + 70); pos[n.id] = { x: X_RIGHT, y, w: 170, h: 52 }; last = y; });
  const width = X_RIGHT + 170 + 24;
  const height = Math.max(...Object.values(pos).map((p) => p.y + p.h)) + 36;
  return { pos, width, height, agents };
}

// One visual link per pair of nodes; arrowheads show which directions carried traffic.
function links(trace) {
  const map = {};
  trace.edges.forEach((e) => {
    const l = (map[[e.from, e.to].sort().join("|")] ||= { a: e.from, b: e.to, count: 0, flagged: 0, edges: [], kinds: new Set() });
    l.count += e.count; l.flagged += e.flagged; l.edges.push(e); l.kinds.add(e.kind);
  });
  return Object.values(map);
}
const linkKind = (l) => (l.a.startsWith("model:") || l.b.startsWith("model:") ? "agent_to_model" : l.a.startsWith("tool:") || l.b.startsWith("tool:") ? "agent_to_tool"
  : l.a.startsWith("user:") || l.b.startsWith("user:") ? "user_to_agent" : "agent_to_agent");
const linkSpans = (trace, l) => trace.spans.filter((sp) => (sp.from === l.a && sp.to === l.b) || (sp.from === l.b && sp.to === l.a));

function flow(trace, ctx) {
  const { pos, width, height, agents } = layout(trace);
  const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, style: `width:100%;max-width:${width}px;height:auto` });
  const defs = s("defs");
  for (const [k, v] of Object.entries({ user_to_agent: KIND.user_to_agent.color, agent_to_agent: KIND.agent_to_agent.color, agent_to_model: KIND.agent_to_model.color, agent_to_tool: KIND.agent_to_tool.color, bad: BAD })) {
    defs.append(s("marker", { id: `ar-${k}`, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, s("path", { d: "M0 0L10 5L0 10z", fill: v })));
  }
  defs.append(s("filter", { id: "soft", x: "-20%", y: "-20%", width: "140%", height: "150%" }, s("feDropShadow", { dx: 0, dy: 5, stdDeviation: 6, "flood-color": "#1e2963", "flood-opacity": 0.13 })));
  svg.append(defs);

  const sel = ctx.selection;
  const selNode = sel?.kind === "node" ? sel.node : null;
  const focus = sel?.kind === "edge" ? [sel.link.a, sel.link.b] : sel?.kind === "span" ? [sel.span.from, sel.span.to] : null;
  const linkFocused = (l) => focus && focus.includes(l.a) && focus.includes(l.b);
  const touchesNode = (l) => !selNode || l.a === selNode || l.b === selNode;
  const parentOf = (id) => { const n = agents.find((x) => x.id === id); return n?.parent ? `agent:${n.parent}` : null; };

  const edgeG = s("g");
  links(trace).forEach((l) => {
    const A = pos[l.a], B = pos[l.b];
    if (!A || !B) return;
    const kind = linkKind(l), bad = l.flagged > 0, color = bad ? BAD : KIND[kind].color;
    // left/right ends so arrowheads can be placed by direction
    const [L, R, lid] = A.x <= B.x ? [A, B, l.a] : [B, A, l.b];
    const toRight = l.edges.some((e) => e.from === lid), toLeft = l.edges.some((e) => e.to === lid);
    let d, lx, ly, startMarker, endMarker;
    const childId = parentOf(l.a) === l.b ? l.a : parentOf(l.b) === l.a ? l.b : null;
    if (kind === "agent_to_agent" && childId) {
      const parent = pos[childId === l.a ? l.b : l.a], child = pos[childId];
      const px = parent.x + 26, cy = child.y + child.h / 2;
      d = `M${px},${parent.y + parent.h} V${cy} H${child.x - 3}`;
      lx = px; ly = (parent.y + parent.h + cy) / 2;
      const down = l.edges.some((e) => e.to === childId), up = l.edges.some((e) => e.from === childId);
      startMarker = up; endMarker = down;
    } else if (kind === "agent_to_agent") {
      const sx = A.x, sy = A.y + A.h / 2, tx = B.x, ty = B.y + B.h / 2, bulge = 90;
      d = `M${sx},${sy} C${sx - bulge},${sy} ${tx - bulge},${ty} ${tx - 3},${ty}`;
      lx = Math.min(sx, tx) - bulge * 0.75; ly = (sy + ty) / 2;
      startMarker = l.edges.some((e) => e.to === l.a); endMarker = l.edges.some((e) => e.to === l.b);
    } else {
      const sx = L.x + L.w, sy = L.y + L.h / 2, tx = R.x, ty = R.y + R.h / 2, mx = (sx + tx) / 2;
      d = `M${sx + 3},${sy} C${mx},${sy} ${mx},${ty} ${tx - 3},${ty}`;
      lx = mx; ly = (sy + ty) / 2;
      startMarker = toLeft; endMarker = toRight;
    }
    const mk = `url(#ar-${bad ? "bad" : kind})`;
    const selected = !!linkFocused(l);
    const g = s("g", { opacity: !sel ? 1 : focus ? (selected ? 1 : 0.15) : touchesNode(l) ? 1 : 0.15, style: "cursor:pointer", onclick: () => ctx.select({ kind: "edge", link: l }) });
    g.append(s("path", { d, fill: "none", stroke: "transparent", "stroke-width": 16 }));
    g.append(s("path", { d, fill: "none", stroke: color, "stroke-width": selected ? 3.6 : bad ? 2.4 : 1.8, class: bad ? "flow-bad" : "flow-anim", "stroke-dasharray": bad ? "6 4" : null, "marker-end": endMarker ? mk : null, "marker-start": startMarker ? mk : null }));
    const label = `${bad ? "⚠ " : ""}${l.count}`;
    const wd = 14 + label.length * 7;
    g.append(s("rect", { x: lx - wd / 2, y: ly - 10, width: wd, height: 20, rx: 10, fill: "#fff", stroke: color }));
    g.append(s("text", { x: lx, y: ly + 4, "text-anchor": "middle", "font-size": 11, "font-weight": 700, fill: color }, label));
    edgeG.append(g);
  });
  svg.append(edgeG);

  trace.nodes.forEach((n) => {
    const p = pos[n.id];
    if (!p) return;
    const isSel = selNode === n.id;
    const near = !sel || isSel || (focus ? focus.includes(n.id) : links(trace).some((l) => (l.a === selNode && l.b === n.id) || (l.b === selNode && l.a === n.id)));
    const g = s("g", { opacity: near ? 1 : 0.25, style: "cursor:pointer", onclick: () => ctx.select({ kind: "node", node: n.id }) });
    const t = n.type;
    const stroke = isSel ? "#4f46e5" : t === "agent" && n.status === "blocked" ? BAD : "#cbd5e1";
    const fill = t === "agent" ? "#fff" : t === "user" ? "#eef2ff" : t === "model" ? "#f0fdfa" : "#fffbeb";
    g.append(s("rect", { x: p.x, y: p.y, width: p.w, height: p.h, rx: 14, fill, stroke, "stroke-width": isSel ? 2.5 : 1.5, filter: "url(#soft)" }));
    const title = n.label.length > 20 ? n.label.slice(0, 19) + "…" : n.label;
    g.append(s("text", { x: p.x + 14, y: p.y + (t === "agent" ? 25 : p.h / 2 + 5), "font-size": 14, "font-weight": 700, fill: "#0f172a" }, (t === "tool" ? "🔧 " : t === "model" ? "◆ " : t === "user" ? "👤 " : "") + title));
    if (t === "agent") {
      g.append(s("text", { x: p.x + 14, y: p.y + 45, "font-size": 11.5, fill: "#64748b" }, `${n.trust} · ${n.status}`));
      const k = scoreKind(n.score);
      g.append(s("rect", { x: p.x + p.w - 50, y: p.y + 9, width: 38, height: 22, rx: 11, fill: { ok: "#dcfce7", warn: "#fef3c7", bad: "#fee2e2" }[k] }));
      g.append(s("text", { x: p.x + p.w - 31, y: p.y + 24.5, "text-anchor": "middle", "font-size": 12.5, "font-weight": 700, fill: { ok: "#15803d", warn: "#b45309", bad: "#b91c1c" }[k] }, n.score));
    }
    svg.append(g);
  });

  const legend = h("div", { class: "legend" },
    Object.entries({ "user ↔ agent": KIND.user_to_agent.color, "agent ↔ agent": KIND.agent_to_agent.color, "agent ↔ model": KIND.agent_to_model.color, "agent ↔ tool": KIND.agent_to_tool.color, "denied / blocked": BAD })
      .map(([l, c]) => h("span", {}, h("i", { style: `background:${c}` }), l)),
    h("span", {}, "number = events · badge = authority score · click anything"));
  return h("div", { class: "card canvas" }, svg, legend);
}

// ---------------------------------------------------------------------------------------------------------------
// Sequence diagram
// ---------------------------------------------------------------------------------------------------------------
function sequence(trace, ctx) {
  const lanes = [
    ...trace.nodes.filter((n) => n.type === "user"), ...trace.nodes.filter((n) => n.type === "agent"),
    ...trace.nodes.filter((n) => n.type === "model"), ...trace.nodes.filter((n) => n.type === "tool"),
  ];
  const laneW = Math.max(128, Math.min(190, 1000 / lanes.length));
  const x = Object.fromEntries(lanes.map((n, i) => [n.id, 70 + i * laneW]));
  const rowH = 40, top = 74;
  const spans = trace.spans;
  const width = 70 + lanes.length * laneW, height = top + spans.length * rowH + 30;
  const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, style: `width:100%;max-width:${width}px;height:auto` });
  svg.append(s("defs", {}, ...Object.entries({ ...Object.fromEntries(Object.entries(KIND).map(([k, v]) => [k, v.color])), bad: BAD }).map(([k, v]) =>
    s("marker", { id: `sq-${k}`, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto" }, s("path", { d: "M0 0L10 5L0 10z", fill: v })))));
  lanes.forEach((n) => {
    const label = n.label.length > 16 ? n.label.slice(0, 15) + "…" : n.label;
    const fill = n.type === "agent" ? "#fff" : n.type === "user" ? "#eef2ff" : n.type === "model" ? "#f0fdfa" : "#fffbeb";
    svg.append(s("line", { x1: x[n.id], x2: x[n.id], y1: 46, y2: height - 10, stroke: "#e2e8f0", "stroke-dasharray": "4 4" }));
    svg.append(s("rect", { x: x[n.id] - 56, y: 10, width: 112, height: 34, rx: 9, fill, stroke: "#cbd5e1" }));
    svg.append(s("text", { x: x[n.id], y: 32, "text-anchor": "middle", "font-size": 12.5, "font-weight": 700 }, label));
  });
  spans.forEach((sp, i) => {
    const y = top + i * rowH + 14;
    const a = x[sp.from], b = x[sp.to];
    if (a == null || b == null) return;
    const bad = flagged(sp);
    const color = bad ? BAD : KIND[sp.kind]?.color || "#64748b";
    const selected = ctx.selection?.kind === "span" && ctx.selection.span === sp;
    const g = s("g", { style: "cursor:pointer", onclick: () => ctx.select({ kind: "span", span: sp }) });
    if (selected) g.append(s("rect", { x: 6, y: y - 22, width: width - 12, height: rowH - 2, rx: 8, fill: "#eef2ff" }));
    g.append(s("rect", { x: 0, y: y - 22, width, height: rowH, fill: "transparent" }));
    g.append(s("line", { x1: a, x2: b > a ? b - 3 : b + 3, y1: y, y2: y, stroke: color, "stroke-width": bad ? 2.4 : 1.8, "stroke-dasharray": sp.boundary === "handoff_return" || sp.boundary === "tool_output" || sp.boundary === "model_output" ? "5 3" : null, "marker-end": `url(#sq-${bad ? "bad" : sp.kind})` }));
    const mid = (a + b) / 2;
    let label = stepLabel(sp);
    if (sp.score_changes.length) label += `  ${sp.score_changes.map((c) => (c.delta > 0 ? "+" : "") + c.delta).join(" ")}`;
    if (sp.entities.length) label += `  · ${sp.entities.length} protected`;
    g.append(s("text", { x: mid, y: y - 7, "text-anchor": "middle", "font-size": 11.5, fill: bad ? BAD : "#334155", "font-weight": bad ? 700 : 500 }, label));
    if (bad) g.append(s("text", { x: b + (b > a ? 10 : -10), y: y + 4, "font-size": 14, "font-weight": 800, fill: BAD, "text-anchor": b > a ? "start" : "end" }, "✕"));
    svg.append(g);
  });
  return h("div", { class: "card canvas" }, svg);
}

// ---------------------------------------------------------------------------------------------------------------
// Agents tab: own vs effective score, counters, and the score of every agent over the session
// ---------------------------------------------------------------------------------------------------------------
const SERIES = ["#4f46e5", "#0f766e", "#d97706", "#db2777", "#0369a1", "#65a30d"];

function scoreChart(trace) {
  const W = 760, H = 270, L = 36, R = 16, T = 14, B = 30;
  const agents = Object.entries(trace.score_series);
  const N = Math.max(1, ...agents.flatMap(([, v]) => v.points.map((p) => p.i)));
  const X = (i) => L + (i / N) * (W - L - R);
  const Y = (v) => T + (1 - v / 100) * (H - T - B);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, style: "width:100%;height:auto" });
  [0, 20, 40, 60, 80, 100].forEach((v) => svg.append(s("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: "#eef2f7" }), s("text", { x: L - 7, y: Y(v) + 4, "text-anchor": "end", "font-size": 10.5, fill: "#94a3b8" }, v)));
  const g = trace.gates;
  const gates = [[g.tool_risk.critical, "critical tools"], [g.tool_risk.high, "high-risk tools"], [g.tool_risk.medium, "medium-risk tools"], [g.block_below, "below this: blocked"]];
  gates.forEach(([v, label], k) => {
    svg.append(s("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: k === 3 ? "#fca5a5" : "#cbd5e1", "stroke-dasharray": "5 4" }),
      s("text", { x: W - R - 4, y: Y(v) - 4, "text-anchor": "end", "font-size": 10, fill: k === 3 ? "#dc2626" : "#94a3b8" }, `${label} ≥ ${v}`.replace("≥", k === 3 ? "<" : "≥")));
  });
  svg.append(s("text", { x: L, y: H - 8, "font-size": 10.5, fill: "#94a3b8" }, "session start"), s("text", { x: W - R, y: H - 8, "text-anchor": "end", "font-size": 10.5, fill: "#94a3b8" }, "score changes, in order →"));
  agents.forEach(([name, v], ai) => {
    const color = SERIES[ai % SERIES.length];
    const pts = [{ i: 0, score: v.initial }, ...v.points, { i: N, score: v.points.length ? v.points[v.points.length - 1].score : v.initial }];
    // step line: a score holds until the next change
    let d = `M${X(0)},${Y(pts[0].score)}`;
    for (let k = 1; k < pts.length; k++) d += ` H${X(pts[k].i)} V${Y(pts[k].score)}`;
    svg.append(s("path", { d, fill: "none", stroke: color, "stroke-width": 2.2, "stroke-linejoin": "round" }));
    v.points.forEach((p) => svg.append(s("circle", { cx: X(p.i), cy: Y(p.score), r: 5, fill: p.delta < 0 ? color : "#fff", stroke: color, "stroke-width": 2 },
      s("title", {}, `${name}: ${p.delta > 0 ? "+" : ""}${p.delta} ${p.rule.replaceAll("_", " ")} → ${p.score}${p.reason ? `\n${p.reason}` : ""}`))));
  });
  const legend = h("div", { class: "legend" }, agents.map(([name], ai) => h("span", {}, h("i", { style: `background:${SERIES[ai % SERIES.length]}` }), name)),
    h("span", {}, "filled dot = penalty · hollow = reward · hover a dot"));
  return h("div", { class: "card" }, h("div", { class: "canvas" }, svg), legend);
}

function agentsTab(trace) {
  const agents = trace.nodes.filter((n) => n.type === "agent");
  const depth = (n) => { let d = 0, p = n.parent; while (p && d < 8) { d++; p = agents.find((a) => a.label === p)?.parent; } return d; };
  const rows = agents.map((a) => {
    const capped = a.effective_score !== a.score;
    return h("tr", {},
      h("td", {}, h("span", { style: `padding-left:${depth(a) * 16}px` }, depth(a) ? h("span", { class: "muted" }, "└ ") : null, h("b", {}, a.label)),
        a.parent ? h("div", { class: "muted", style: `font-size:12px;padding-left:${depth(a) * 16 + 18}px` }, `delegated by ${a.parent}`) : h("div", { class: "muted", style: "font-size:12px" }, "top-level agent")),
      h("td", { style: "min-width:150px" }, scoreBar(a.score, a.ceiling)),
      h("td", {}, capped ? h("span", {}, pill(a.effective_score, scoreKind(a.effective_score)), h("div", { class: "muted", style: "font-size:11.5px" }, "capped by parent")) : h("span", { class: "muted" }, "same")),
      h("td", {}, pill(a.trust, a.trust === "trusted" ? "ok" : a.trust === "untrusted" ? "bad" : "mute")),
      h("td", {}, a.tool_calls), h("td", {}, a.denied ? pill(a.denied, "bad") : "0"), h("td", {}, a.violations ? pill(a.violations, "warn") : "0"),
      h("td", {}, a.status === "blocked" ? pill("blocked", "bad") : pill(a.status, "mute")));
  });
  return h("div", {},
    h("div", { class: "card table-card", style: "margin-bottom:14px" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Agent", "Own score", "Effective (tool gate)", "Trust", "Tool calls", "Denied", "Violations", "Status"].map((t) => h("th", {}, t)))), h("tbody", {}, rows))),
    h("p", { class: "muted", style: "margin:0 0 12px" }, "The tool gate uses the effective score: the lower of the agent's own score and every score above it in the delegation chain."),
    scoreChart(trace));
}

// ---------------------------------------------------------------------------------------------------------------
// Timeline + receipts
// ---------------------------------------------------------------------------------------------------------------
function timeline(trace, ctx) {
  const spans = trace.spans.filter((sp) => !sp.synthetic);
  return h("div", { class: "card table-card" }, spans.map((sp) => spanItem(sp, ctx.selection?.kind === "span" && ctx.selection.span === sp, () => ctx.select({ kind: "span", span: sp }))));
}

function receiptSummary(r) {
  const p = r.payload || {};
  if (r.type === "authority") return `${p.agent}: ${String(p.rule).replaceAll("_", " ")} ${p.delta > 0 ? "+" : ""}${p.delta} → score ${p.score}`;
  if (p.boundary === "session_end") return `session ended · verdict ${p.verdict?.blocked ? "BLOCKED" : "ok"}`;
  return `${p.agent}: ${p.boundary} → ${p.outcome}${p.tool ? ` (${p.tool})` : ""}`;
}

function receipts(trace) {
  const box = h("div", {}, h("div", { class: "muted" }, "Loading…"));
  api.get(`/api/traces/${trace.session.id}/receipts`).then((data) => {
    const v = data.verify;
    box.replaceChildren(
      h("div", { class: `banner ${v.ok ? "ok" : "bad"}` }, v.ok ? "✓" : "✕", `${v.receipt_count} receipts · ${v.reason}`,
        h("span", { style: "margin-left:auto", class: "row" },
          h("button", { class: "btn", onclick: () => { const a = h("a", { href: URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })), download: `receipts-${trace.session.id}.json` }); a.click(); } }, "Export JSON"))),
      h("div", { class: "card table-card" }, h("table", {},
        h("thead", {}, h("tr", {}, ["#", "Type", "Decision", "Hash", "Previous"].map((t) => h("th", {}, t)))),
        h("tbody", {}, data.receipts.map((r) => h("tr", {}, h("td", {}, r.seq), h("td", {}, pill(r.type, r.type === "authority" ? "warn" : "mute")), h("td", {}, receiptSummary(r)),
          h("td", { class: "mono" }, r.hash.slice(0, 12) + "…"), h("td", { class: "mono muted" }, r.prev_hash.slice(0, 12) + "…")))))),
      h("p", { class: "muted" }, "Each receipt's hash covers the one before it. Change any past decision and every later hash stops matching."));
  }).catch((e) => box.replaceChildren(h("div", { class: "empty" }, e.message)));
  return box;
}

// ---------------------------------------------------------------------------------------------------------------
// the whole trace page
// ---------------------------------------------------------------------------------------------------------------
export function traceView(trace) {
  const root = h("div");
  const ctx = { selection: null, tab: "flow", select(sel) { ctx.selection = sel; draw(); } };
  const tabs = [["flow", "Flow"], ["sequence", "Sequence"], ["timeline", "Timeline"], ["agents", "Agents & scores"], ["receipts", "Receipts"]];

  const v = trace.verdict;
  const banner = h("div", { class: `banner ${v.blocked ? "bad" : "ok"}` }, v.blocked ? "✕ Final answer blocked" : "✓ Final answer released", h("span", { style: "font-weight:400" }, v.blocked ? `— ${v.reason}` : "— every agent stayed above the trust floor"));
  const sm = trace.summary;
  const facts = h("div", { class: "facts" },
    h("span", {}, "User ", h("b", {}, trace.session.user)), h("span", {}, "Started ", h("b", {}, when(trace.session.started_at))),
    h("span", {}, h("b", {}, sm.agents), " agents"), h("span", {}, h("b", {}, sm.spans), " events"), h("span", {}, h("b", {}, sm.entities_protected), " values protected"),
    h("span", {}, h("b", {}, sm.tool_calls), " tool calls"), h("span", {}, h("b", {}, sm.flagged), " denied/blocked"), h("span", {}, h("b", {}, num(sm.tokens)), " tokens"),
    h("span", {}, "Receipts ", pill(trace.receipts.ok ? "chain intact" : "BROKEN", trace.receipts.ok ? "ok" : "bad")));
  const tabBar = h("div", { class: "tabs" });
  const body = h("div");
  root.append(banner, facts, tabBar, body);

  function panel() {
    const sel = ctx.selection;
    const box = h("div", { class: "card panel" });
    if (!sel) { box.append(h("div", { class: "muted" }, "Click an agent, a connection or a step to see what happened, what was protected and why.")); return box; }
    if (sel.kind === "span") { box.append(h("h3", {}, `${nameOf(sel.span.from)} → ${nameOf(sel.span.to)}`), spanDetail(sel.span)); return box; }
    let list, title;
    if (sel.kind === "edge") {
      const l = sel.link;
      list = linkSpans(trace, l).filter((sp) => !sp.synthetic);
      title = `${nameOf(l.a)} ↔ ${nameOf(l.b)}`;
    } else {
      const n = trace.nodes.find((x) => x.id === sel.node);
      list = trace.spans.filter((sp) => !sp.synthetic && (sp.from === n.id || sp.to === n.id));
      title = n.label;
      if (n.type === "agent") box.append(h("div", { class: "kv" }, h("span", {}, "Score"), h("span", {}, `${n.score} / ${n.ceiling} (effective ${n.effective_score})`), h("span", {}, "Trust"), h("span", {}, n.trust), h("span", {}, "Parent"), h("span", {}, n.parent || "— top level —")));
    }
    box.prepend(h("h3", {}, title), h("div", { class: "muted", style: "margin-bottom:6px" }, `${list.length} event${list.length === 1 ? "" : "s"}`));
    list.forEach((sp) => box.append(spanItem(sp, false, () => ctx.select({ kind: "span", span: sp }))));
    return box;
  }

  function draw() {
    tabBar.replaceChildren(...tabs.map(([k, l]) => h("button", { class: ctx.tab === k ? "on" : "", onclick: () => { ctx.tab = k; ctx.selection = null; draw(); } }, l)));
    if (ctx.tab === "receipts") { body.replaceChildren(receipts(trace)); return; }
    if (ctx.tab === "agents") { body.replaceChildren(agentsTab(trace)); return; }
    const main = ctx.tab === "flow" ? flow(trace, ctx) : ctx.tab === "sequence" ? sequence(trace, ctx) : timeline(trace, ctx);
    const showPanel = ctx.tab !== "timeline" && ctx.selection;
    const hint = ctx.tab === "timeline" ? "Click a step to expand it." : "Click an agent, a connection or a step to see what happened, what was protected and why.";
    body.replaceChildren(h("div", { class: "muted", style: "margin:-6px 0 10px;font-size:13px" }, hint),
      h("div", { class: showPanel ? "trace-layout" : "" }, main, showPanel ? panel() : null));
  }
  draw();
  return root;
}
