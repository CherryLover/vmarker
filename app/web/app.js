// ============================================================================
//  app —— 启动 + 路由。每个视图是 async render(root, 参数)
// ============================================================================
import { api, esc } from "/static/ui.js";
import * as home from "/static/views/home.js";
import * as project from "/static/views/project.js";
import * as series from "/static/views/series.js";
import * as settings from "/static/views/settings.js";

const ROUTES = [
  [/^\/p\/([^/]+)$/, project.render, "/"],
  [/^\/s\/([^/]+)$/, series.renderOne, "/series"],
  [/^\/series$/, series.renderList, "/series"],
  [/^\/settings/, settings.render, "/settings"],
  [/^\/$/, home.render, "/"],
];
const root = document.getElementById("root");

export function go(url) { history.pushState(null, "", url); render(); }

async function render() {
  const [re, view, nav] = ROUTES.find(([r]) => r.test(location.pathname)) || ROUTES.at(-1);
  document.querySelectorAll("[data-nav]").forEach((a) => a.toggleAttribute("aria-current", false));
  document.querySelector(`[data-nav="${nav}"]`).setAttribute("aria-current", "page");
  // 每次换一个新容器：旧视图的异步回调只会写到已移除的节点上
  const el = Object.assign(document.createElement("div"), { className: "col" });
  root.replaceChildren(el);
  try { await view(el, location.pathname.match(re)?.[1]); } catch (e) { el.innerHTML = `<section class="card"><h2>出错了</h2><p class="bad">${esc(e.message)}</p></section>`; }
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[href^='/']");
  if (!a || a.target || e.metaKey || e.ctrlKey || /^\/(api|auth)/.test(a.getAttribute("href"))) return;
  e.preventDefault();
  go(a.getAttribute("href"));
});
window.addEventListener("popstate", render);

const me = await api("/api/v1/me");
document.getElementById("user").innerHTML = `<span class="muted small">${esc(me.name)}</span>
  <form method="post" action="/auth/logout"><button class="btn sm">退出</button></form>`;
render();
