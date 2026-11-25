// ============================================================================
//  md —— 极简 Markdown 渲染：先整体转义，再识别结构，所以 AI 的输出无法注入 HTML
// ============================================================================
import { esc } from "/static/ui.js";

const inline = (s) => s
  .replace(/`([^`]+)`/g, "<code>$1</code>")
  .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
  .replace(/&lt;br\s*\/?&gt;/g, "<br>")
  .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
const table = (rows) => {
  const [head, , ...body] = rows;
  const tr = (l, t) => `<tr>${cells(l).map((c) => `<${t}>${c}</${t}>`).join("")}</tr>`;
  return `<div class="tbl"><table><thead>${tr(head, "th")}</thead><tbody>${body.map((l) => tr(l, "td")).join("")}</tbody></table></div>`;
};
const list = (tag, strip) => (rows) => `<${tag}>${rows.map((l) => `<li>${inline(l.replace(strip, ""))}</li>`).join("")}</${tag}>`;

// 每条规则：连续匹配的行归为一块
const BLOCKS = [
  [/^\s*\|.*\|\s*$/, (rows) => (rows.length > 1 ? table(rows) : `<p>${inline(rows[0])}</p>`)],
  [/^\s*[-*] /, list("ul", /^\s*[-*] /)],
  [/^\s*\d+[.)] /, list("ol", /^\s*\d+[.)] /)],
  [/^&gt; ?/, (rows) => `<blockquote>${rows.map((l) => inline(l.replace(/^&gt; ?/, ""))).join("<br>")}</blockquote>`],
  [/^-{3,}\s*$/, () => "<hr>"],
  [/^#{1,6} /, (rows) => rows.map((l) => {
    const n = Math.min(3, l.match(/^#+/)[0].length);
    return `<h${n}>${inline(l.replace(/^#+ /, ""))}</h${n}>`;
  }).join("")],
];
const PLAIN = [/\S/, (rows) => `<p>${rows.map(inline).join("<br>")}</p>`];
const ruleOf = (l) => BLOCKS.find(([re]) => re.test(l)) || PLAIN;

function blocks(text) {
  const out = [];
  let rule = null, rows = [];
  const flush = () => { if (rows.length) out.push(rule[1](rows)); rows = []; };
  for (const l of text.split("\n")) {
    const next = l.trim() ? ruleOf(l) : null;
    if (next !== rule) { flush(); rule = next; }
    if (next) rows.push(l);
  }
  flush();
  return out.join("");
}

export function md(src) {
  return esc(src).split(/^```[^\n]*\n/m).map((part, i) =>
    (i % 2 ? `<pre><code>${part.replace(/\n$/, "")}</code></pre>` : blocks(part))).join("");
}

// 对话消息：把 <file> 块折叠成文件卡片
export function mdMessage(src) {
  const re = /^<file name="([^"\n]+)">[ \t]*\n([\s\S]*?)(?:^<\/file>[ \t]*$|$(?![\s\S]))/gm;
  let out = "", last = 0;
  for (const m of src.matchAll(re)) {
    out += md(src.slice(last, m.index));
    out += `<details class="filecard"><summary>📄 ${esc(m[1])}</summary><div class="md">${md(m[2])}</div></details>`;
    last = m.index + m[0].length;
  }
  return out + md(src.slice(last));
}
