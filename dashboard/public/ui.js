// Tiny DOM helpers and formatters shared by the pages.

const SVG_NS = "http://www.w3.org/2000/svg";

function build(el, attrs, kids) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.setAttribute("class", v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export const h = (tag, attrs, ...kids) => build(document.createElement(tag), attrs, kids);
export const s = (tag, attrs, ...kids) => build(document.createElementNS(SVG_NS, tag), attrs, kids);

export const pill = (text, kind = "mute") => h("span", { class: `pill ${kind}` }, text);
export const chip = (text, cls = "") => h("span", { class: `chip ${cls}` }, text);

export function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function ago(iso) {
  if (!iso) return "never";
  const sec = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export const num = (n) => Number(n || 0).toLocaleString();
export const scoreKind = (v) => (v >= 70 ? "ok" : v >= 40 ? "warn" : "bad");

export function scoreBar(value, ceiling = 100) {
  const pct = Math.max(0, Math.min(100, (value / (ceiling || 100)) * 100));
  return h("div", { class: "score" }, h("div", { class: `bar ${scoreKind(value)}`, style: "flex:1" }, h("i", { style: `width:${pct}%` })), h("b", {}, value));
}

// Show vault tokens (tok_name_ab12...) as highlighted chips inside text.
export function tokenText(text) {
  const out = [];
  for (const part of String(text ?? "").split(/(tok_[a-z_]+_[0-9a-f]{12})/g)) {
    out.push(/^tok_[a-z_]+_[0-9a-f]{12}$/.test(part) ? h("span", { class: "tok" }, part) : part);
  }
  return h("div", { class: "tokline" }, out);
}

export const OUTCOME = {
  allowed: ["allowed", "ok"],
  tokenized: ["protected", "acc"],
  logged: ["flagged", "warn"],
  denied: ["denied", "bad"],
  blocked: ["blocked", "bad"],
  approval_required: ["needs approval", "warn"],
};
export const outcomePill = (o) => pill(...(OUTCOME[o] || [o, "mute"]));

export const api = {
  async get(path) {
    const r = await fetch(path, { credentials: "same-origin" });
    if (r.status === 401) { location.hash = "#/login"; throw new Error("signed out"); }
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.statusText);
    return data;
  },
};

export const icons = {
  logo: `<svg width="28" height="28" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#4f46e5"/><path d="M16 6l8 3v7c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V9z" fill="none" stroke="#fff" stroke-width="2"/></svg>`,
  overview: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>`,
  traces: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="M7 6h10M6 8l5 8M18 8l-5 8"/></svg>`,
  agents: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="8" width="16" height="11" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01"/></svg>`,
  trust: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 17l5-5 4 4 8-9"/><path d="M15 7h5v5"/></svg>`,
  users: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.5-3.5 3-5.5 6.5-5.5s6 2 6.5 5.5"/><path d="M16 4.5a3.5 3.5 0 010 7M18.5 14.5c1.8.7 3 2.4 3.3 5"/></svg>`,
  test: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3h6M10 3v6L4.5 19a1.5 1.5 0 001.3 2h12.4a1.5 1.5 0 001.3-2L14 9V3"/><path d="M7.5 14h9"/></svg>`,
  policies: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/></svg>`,
};

export function barList(items, empty = "Nothing yet") {
  if (!items.length) return h("div", { class: "muted" }, empty);
  const max = Math.max(1, ...items.map((i) => i.value));
  return h("div", { class: "bars" }, items.map((i) => h("div", { class: "b" }, h("span", { class: "mono", style: "overflow:hidden;text-overflow:ellipsis" }, i.label),
    h("div", { class: "bar" }, h("i", { style: `width:${(i.value / max) * 100}%` })), h("span", {}, num(i.value)))));
}

// A simple line chart: points = [{label, y}], y in 0..max.
export function lineChart(points, { max = 100, color = "#4f46e5", height = 170, unit = "" } = {}) {
  const W = 640, L = 34, R = 12, T = 12, B = 24;
  const n = Math.max(points.length, 1);
  const X = (i) => L + (n === 1 ? (W - L - R) / 2 : (i / (n - 1)) * (W - L - R));
  const Y = (v) => T + (1 - Math.min(v, max) / max) * (height - T - B);
  const svg = s("svg", { viewBox: `0 0 ${W} ${height}`, style: "width:100%;height:auto" });
  [0, 0.5, 1].forEach((f) => {
    const v = Math.round(max * f);
    svg.append(s("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: "#e2e8f0" }), s("text", { x: L - 6, y: Y(v) + 4, "text-anchor": "end", "font-size": 10.5, fill: "#94a3b8" }, v));
  });
  if (points.length) {
    svg.append(s("path", { d: points.map((p, i) => `${i ? "L" : "M"}${X(i)},${Y(p.y)}`).join(" "), fill: "none", stroke: color, "stroke-width": 2.2, "stroke-linejoin": "round" }));
    points.forEach((p, i) => svg.append(s("circle", { cx: X(i), cy: Y(p.y), r: 3.8, fill: "#fff", stroke: color, "stroke-width": 2 }, s("title", {}, `${p.label}: ${p.y}${unit}`))));
    svg.append(s("text", { x: L, y: height - 6, "font-size": 10.5, fill: "#94a3b8" }, points[0].label), s("text", { x: W - R, y: height - 6, "text-anchor": "end", "font-size": 10.5, fill: "#94a3b8" }, points[points.length - 1].label));
  }
  return svg;
}

export function ring(value, size = 120, label = "") {
  const r = size / 2 - 10, c = 2 * Math.PI * r, k = scoreKind(value);
  const col = { ok: "#22c55e", warn: "#f59e0b", bad: "#ef4444" }[k];
  return s("svg", { width: size, height: size, viewBox: `0 0 ${size} ${size}` },
    s("circle", { cx: size / 2, cy: size / 2, r, fill: "none", stroke: "#eef2f7", "stroke-width": 10 }),
    s("circle", { cx: size / 2, cy: size / 2, r, fill: "none", stroke: col, "stroke-width": 10, "stroke-linecap": "round", "stroke-dasharray": `${(value / 100) * c} ${c}`, transform: `rotate(-90 ${size / 2} ${size / 2})` }),
    s("text", { x: size / 2, y: size / 2 + 2, "text-anchor": "middle", "font-size": size / 3.2, "font-weight": 800, fill: "#0f172a" }, value),
    s("text", { x: size / 2, y: size / 2 + size / 5, "text-anchor": "middle", "font-size": 11, fill: "#64748b" }, label));
}

export const TYPE_COLORS = ["#4f46e5", "#0f766e", "#d97706", "#7c3aed", "#db2777", "#0369a1", "#65a30d", "#dc2626"];
