// 文件面板：列表 / 预览 / 编辑 / 历史版本（项目和系列共用）
import { api, dialog, esc, on, seg, size, toast, when } from "/static/ui.js";
import { md } from "/static/md.js";

export function filesPanel(root, oid) {
  const base = `/api/v1/files/${oid}`;
  const url = (n) => `${base}/${seg(n)}`;
  const owner = `/api/v1/${oid[0] === "p" ? "projects" : "series"}/${oid}`;

  async function list() {
    const { files } = await api(owner);
    root.innerHTML = `<div class="row between"><h2>文件</h2><button class="btn sm" data-new>新建文件</button></div>
      <div>${files.map((f) => `<div class="item"><button class="btn sm" data-open="${esc(f.name)}">📄 ${esc(f.name)}</button>
        <span class="muted small">${size(f.size)} · ${when(f.updated_at)}</span></div>`).join("") || '<p class="muted">还没有文件。让左边的 AI 整理，或手动新建。</p>'}</div>`;
    on(root, "[data-open]", "click", (b) => open(b.dataset.open));
    on(root, "[data-new]", "click", () => dialog("新建文件", '<label>文件名<input name="name" required placeholder="备注.md"></label>', "下一步", (f) => {
      const name = f.name.trim().replace(/(\.md)?$/, ".md");
      if (files.some((x) => x.name === name)) throw new Error("已有同名文件");
      edit(name, "");
    }));
  }

  async function open(name) {
    const { content } = await api(url(name));
    root.innerHTML = `<div class="row between"><h2>${esc(name)}</h2><div class="row">
      <button class="btn sm" data-back>返回</button><button class="btn sm" data-hist>历史</button>
      <button class="btn sm danger" data-del>删除</button><button class="btn sm primary" data-edit>编辑</button></div></div><div class="md">${md(content)}</div>`;
    on(root, "[data-back]", "click", list);
    on(root, "[data-edit]", "click", () => edit(name, content));
    on(root, "[data-hist]", "click", () => hist(name));
    on(root, "[data-del]", "click", async () => {
      if (!confirm(`删除 ${name}？旧版会留在 .history。`)) return;
      await api(url(name), { method: "DELETE" });
      await list();
    });
  }

  function edit(name, content) {
    root.innerHTML = `<h2>编辑 ${esc(name)}</h2><textarea class="editor" aria-label="文件内容"></textarea>
      <div class="row"><button class="btn primary" data-save>保存</button><button class="btn" data-back>取消</button></div>`;
    const area = root.querySelector("textarea");
    area.value = content;
    on(root, "[data-back]", "click", list);
    on(root, "[data-save]", "click", async () => {
      await api(url(name), { method: "PUT", body: { content: area.value } });
      toast("已保存");
      await open(name);
    });
  }

  async function hist(name) {
    const rows = await api(`${url(name)}/history`);
    root.innerHTML = `<div class="row between"><h2>${esc(name)} 的历史版本</h2><button class="btn sm" data-back>返回</button></div>
      ${rows.map((r) => `<div class="item"><button class="btn sm" data-v="${esc(r.version)}">${esc(r.version)}（UTC）</button></div>`).join("") || '<p class="muted">没有旧版。</p>'}`;
    on(root, "[data-back]", "click", () => open(name));
    on(root, "[data-v]", "click", async (b) => edit(name, (await api(`${url(name)}/history/${b.dataset.v}`)).content));
  }

  list().catch((e) => toast(e.message, "error"));
  return { list, open, edit };
}
