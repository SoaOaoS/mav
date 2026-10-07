/* Mav web app — Markdown (zero dependency, HTML-escaped first).
   One of the classic scripts index.html loads in order (5/12); they share
   one global scope, like the single app.js they came from. */

/* ================================================================
   7. Markdown (zero dependency, HTML-escaped first)
   ================================================================ */
function splitRow(line) {
  let s = String(line).trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}
function isTableSep(line) {
  const cells = splitRow(line);
  return cells.length > 0 && cells.every((c) => /^:?-{2,}:?$/.test(c));
}
function renderTable(lines) {
  const header = splitRow(lines[0]);
  const aligns = splitRow(lines[1]).map((c) =>
    /^:-+:$/.test(c) ? "center" : /^-+:$/.test(c) ? "right" : "",
  );
  const cls = (i) => (aligns[i] ? ` class="md-${aligns[i]}"` : "");
  const th = header.map((c, i) => `<th${cls(i)}>${inline(c)}</th>`).join("");
  const rows = lines
    .slice(2)
    .map(splitRow)
    .map(
      (r) =>
        "<tr>" +
        header
          .map(
            (_, i) => `<td${cls(i)}>${inline(r[i] == null ? "" : r[i])}</td>`,
          )
          .join("") +
        "</tr>",
    )
    .join("");
  return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${th}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
/* ---- Rich directives: [[chart:SYMBOL:PERIOD]] and [[file:PATH]] ----
   Rendered on a line of their own. The chart pulls /api/chart (Yahoo
   proxy), the file becomes a download card to /api/download. */
const CHART_PERIODS = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"];

function chartBlock(spec) {
  const parts = String(spec).split(":");
  const sym = (parts[0] || "").trim();
  let period = (parts[1] || "1mo").trim().toLowerCase();
  if (!CHART_PERIODS.includes(period)) period = "1mo";
  if (!sym) return "";
  const uid = "ch" + Math.random().toString(36).slice(2, 9);
  return `<figure class="md-chart" id="${uid}" data-symbol="${esc(sym)}" data-range="${esc(period)}">
    <div class="md-chart-head"><span class="md-chart-name">${esc(sym)}</span><span class="md-chart-quote"></span></div>
    <div class="md-chart-plot"><div class="md-chart-load">Loading chart…</div></div>
    <figcaption class="md-chart-foot"><span class="md-chart-range"></span><button type="button" class="chart-refresh" title="Refresh">${I("refresh")}</button></figcaption>
  </figure>`;
}

function fileCardHtml(raw) {
  const name = String(raw).trim();
  const base = name.split(/[\\/]/).pop() || name;
  const ext = (base.match(/\.([a-z0-9]+)$/i) || [null, ""])[1].toLowerCase();
  const url = "/api/download?path=" + encodeURIComponent(name);
  return `<a class="md-file" href="${escapeHtml(url)}" download="${escapeHtml(base)}">
    <span class="md-file-ico">${I("download")}</span>
    <span class="md-file-main"><strong>${esc(base)}</strong><span>${ext ? ext.toUpperCase() + " · " : ""}Click to download</span></span>
  </a>`;
}

function fmtChartNum(v, cur) {
  if (v == null || isNaN(v)) return "—";
  const abs = Math.abs(v);
  const digits = abs >= 1000 ? 0 : abs >= 1 ? 2 : 4;
  const n = Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
  return cur ? `${n} ${cur}` : n;
}

function sparkSvg(closes, positive, uid) {
  const w = 640,
    h = 180,
    pad = 10;
  const n = closes.length;
  if (n < 2) return "";
  let lo = Math.min(...closes),
    hi = Math.max(...closes);
  if (hi === lo) hi = lo + 1;
  const x = (i) => pad + (i * (w - 2 * pad)) / (n - 1);
  const y = (v) => h - pad - ((v - lo) / (hi - lo)) * (h - 2 * pad);
  const pts = closes.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const line = "M" + pts.join(" L");
  const area = `${line} L${x(n - 1).toFixed(1)},${(h - pad).toFixed(1)} L${x(0).toFixed(1)},${(h - pad).toFixed(1)} Z`;
  const col = positive ? "var(--ok)" : "var(--danger)";
  const gid = (uid || "ch") + "g";
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="md-chart-svg" aria-hidden="true">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${col}" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="${col}" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${area}" fill="url(#${gid})"/>
    <path d="${line}" fill="none" stroke="${col}" stroke-width="2" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

async function loadChart(fig) {
  const sym = fig.dataset.symbol,
    range = fig.dataset.range;
  const plot = fig.querySelector(".md-chart-plot");
  const quote = fig.querySelector(".md-chart-quote");
  const foot = fig.querySelector(".md-chart-range");
  try {
    const r = await fetch(
      `/api/chart?symbol=${encodeURIComponent(sym)}&range=${encodeURIComponent(range)}`,
      { headers: { Accept: "application/json" } },
    );
    if (!r.ok) throw new Error("no data");
    const d = await r.json();
    if (!d.series || d.series.length < 2) throw new Error("no series");
    const up = (d.range_pct || 0) >= 0;
    plot.innerHTML = sparkSvg(d.series, up, fig.id);
    const chg = d.range_pct != null ? d.range_pct : 0;
    quote.innerHTML = `<span class="md-chart-price">${esc(fmtChartNum(d.price, d.currency))}</span><span class="md-chart-chg ${up ? "up" : "down"}">${up ? "+" : ""}${chg.toFixed(2)}%</span>`;
    fig.querySelector(".md-chart-name").textContent = d.name || sym;
    foot.textContent = `${range} · ${d.symbol || sym}`;
    fig.classList.toggle("is-up", up);
    fig.classList.toggle("is-down", !up);
  } catch (_) {
    plot.innerHTML = `<div class="md-chart-load">Chart unavailable</div>`;
  }
}

function hydrateCharts(root = document) {
  $$(".md-chart:not([data-loaded])", root).forEach((fig) => {
    fig.dataset.loaded = "1";
    loadChart(fig);
  });
}

function inline(s) {
  let t = escapeHtml(s);
  t = t.replace(/`([^`\n]+)`/g, '<code class="md-inline">$1</code>');
  t = t.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  t = t.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
  t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  t = t.replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");
  t = t.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
  t = t.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, src) => {
    const rawSrc = src.replace(/&amp;/g, "&");
    const url = /^(https?:|data:image)/i.test(rawSrc)
      ? rawSrc
      : /^media:/i.test(rawSrc)
        ? "/api/media/by-name?name=" + encodeURIComponent(rawSrc.slice(6))
        : "/api/asset?path=" + encodeURIComponent(rawSrc);
    return `<img class="md-img" src="${escapeHtml(url)}" alt="${alt}" loading="lazy">`;
  });
  t = t.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  t = t.replace(
    /(^|[\s(])(https?:\/\/[^\s<)]+)/g,
    '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>',
  );
  return t;
}
function mdToHtml(src) {
  let text = String(src == null ? "" : src);
  const codeBlocks = [];
  const codeHtml = (lang, code) =>
    `<div class="code-block"><div class="code-head"><span>${escapeHtml(lang || "code")}</span><button type="button" class="code-copy">${I("copy")} Copy</button></div><pre class="md-code"><code>${escapeHtml(code.replace(/\n$/, ""))}</code></pre></div>`;
  text = text.replace(/```([\w+-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    codeBlocks.push(codeHtml(lang, code));
    return `\u0000CODE${codeBlocks.length - 1}\u0000`;
  });
  // Streaming: an unterminated fence still renders as code.
  text = text.replace(/```([\w+-]*)\n([\s\S]*)$/, (_, lang, code) => {
    codeBlocks.push(codeHtml(lang, code));
    return `\u0000CODE${codeBlocks.length - 1}\u0000`;
  });

  const renderTableAt = (lines, i) => {
    if (!/^\s*\|.*\|\s*$/.test(lines[i])) return null;
    if (i + 1 >= lines.length || !isTableSep(lines[i + 1])) return null;
    const block = [];
    let j = i;
    while (j < lines.length && /^\s*\|.*\|\s*$/.test(lines[j]))
      block.push(lines[j++]);
    return { html: renderTable(block), next: j };
  };

  const renderBlocks = (lines) => {
    let out = "";
    let para = [];
    const flush = () => {
      if (para.length) out += `<p class="md-p">${para.join("<br>")}</p>`;
      para = [];
    };
    let i = 0;
    while (i < lines.length) {
      const raw = lines[i];
      const line = raw.trim();
      if (!line) {
        flush();
        i++;
        continue;
      }
      let m = line.match(/^\u0000CODE(\d+)\u0000$/);
      if (m) {
        flush();
        out += codeBlocks[Number(m[1])] || "";
        i++;
        continue;
      }
      m = line.match(/^\[\[chart:([^\]\s]+)\]\]$/i);
      if (m) {
        flush();
        out += chartBlock(m[1]);
        i++;
        continue;
      }
      m = line.match(/^\[\[(?:file|download):(.+?)\]\]$/i);
      if (m) {
        flush();
        out += fileCardHtml(m[1].trim());
        i++;
        continue;
      }
      m = raw.match(/^(#{1,6})\s+(.*)$/);
      if (m) {
        flush();
        const lvl = Math.min(m[1].length + 1, 6);
        out += `<h${lvl} class="md-h">${inline(m[2])}</h${lvl}>`;
        i++;
        continue;
      }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(raw)) {
        flush();
        out += '<hr class="md-hr">';
        i++;
        continue;
      }
      const t = renderTableAt(lines, i);
      if (t) {
        flush();
        out += t.html;
        i = t.next;
        continue;
      }
      if (/^\s*>\s?/.test(raw)) {
        flush();
        const inner = [];
        let j = i;
        while (j < lines.length && /^\s*>\s?/.test(lines[j]))
          inner.push(lines[j++].replace(/^\s*>\s?/, ""));
        out += `<blockquote class="md-quote">${renderBlocks(inner)}</blockquote>`;
        i = j;
        continue;
      }
      if (/^(\s*)([-*+]|\d+[.)])\s+/.test(raw)) {
        flush();
        const items = [];
        let j = i;
        while (j < lines.length && /^(\s*)([-*+]|\d+[.)])\s+/.test(lines[j])) {
          const mm = lines[j].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
          items.push({
            indent: mm[1].replace(/\t/g, "    ").length,
            ordered: /^\d/.test(mm[2]),
            text: mm[3],
          });
          j++;
        }
        out += renderList(items);
        i = j;
        continue;
      }
      para.push(inline(raw));
      i++;
    }
    flush();
    return out;
  };
  return renderBlocks(text.split("\n")).replace(
    /\u0000CODE(\d+)\u0000/g,
    (_, i) => codeBlocks[Number(i)] || "",
  );
}
function renderList(items) {
  const root = { children: [] };
  const stack = [{ indent: -1, node: root }];
  for (const it of items) {
    while (stack.length > 1 && it.indent <= stack[stack.length - 1].indent)
      stack.pop();
    const node = { ordered: it.ordered, text: it.text, children: [] };
    stack[stack.length - 1].node.children.push(node);
    stack.push({ indent: it.indent, node });
  }
  const walk = (nodes) => {
    let out = "";
    let i = 0;
    while (i < nodes.length) {
      const ordered = nodes[i].ordered;
      let j = i;
      while (j < nodes.length && nodes[j].ordered === ordered) j++;
      const tag = ordered ? "ol" : "ul";
      out += `<${tag} class="md-list">`;
      for (let k = i; k < j; k++) {
        let txt = nodes[k].text;
        const task = txt.match(/^\[( |x|X)\]\s+(.*)$/);
        const body = task
          ? `${task[1] === " " ? "☐" : "☑"} ${inline(task[2])}`
          : inline(txt);
        out += `<li>${body}${nodes[k].children.length ? walk(nodes[k].children) : ""}</li>`;
      }
      out += `</${tag}>`;
      i = j;
    }
    return out;
  };
  return walk(root.children);
}
