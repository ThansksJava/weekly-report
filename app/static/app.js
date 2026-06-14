/* 周报系统前端逻辑:登录、列表、可自定义编辑器、导出、邮件 */
"use strict";

const $ = (sel) => document.querySelector(sel);

let me = null;          // 当前用户
let reports = [];       // 周报列表(摘要)
let current = null;     // 当前编辑中的周报(完整对象)
let optionSets = {};    // 用户选项集:名称 -> 候选值
let templates = [];     // 用户的模板列表(含 id/name/title/greeting/subtitle/sections)
let defaultTemplateId = ""; // 默认模板 id
let dirty = false;
let saveTimer = null;

/* ---------------- API ---------------- */
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

/* ---------------- 工具 ---------------- */
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove("show"), 2400);
}

function uid() { return Math.random().toString(36).slice(2, 10); }

function miniBtn(text, onClick, extraClass = "") {
  const b = document.createElement("button");
  b.className = "mini-btn" + (extraClass ? " " + extraClass : "");
  b.textContent = text;
  b.addEventListener("click", onClick);
  return b;
}

function fmtDot(iso) { return (iso || "").replaceAll("-", "."); }

function setDirty(v) {
  dirty = v;
  const el = $("#save-state");
  el.textContent = v ? "未保存…" : "已保存";
  el.classList.toggle("dirty", v);
  if (v) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveReport, 1500); // 自动保存
  }
}

/* ---------------- 登录视图 ---------------- */
let registerMode = false;

function showLogin() {
  $("#view-login").classList.remove("hidden");
  $("#view-app").classList.add("hidden");
}

async function showApp() {
  $("#view-login").classList.add("hidden");
  $("#view-app").classList.remove("hidden");
  $("#user-name").textContent = me.display_name || me.username;
  $("#user-avatar").textContent = (me.display_name || me.username).slice(0, 1).toUpperCase();
  optionSets = await api("/api/options");
  await loadTemplates();
  initDatePickers();
}

async function loadTemplates() {
  const data = await api("/api/templates");
  templates = data.templates || [];
  defaultTemplateId = data.default_template_id || "";
}

/* ---------------- 日期组件(flatpickr) ---------------- */
let fpStart = null, fpEnd = null;

function initDatePickers() {
  if (fpStart) return;
  const cfg = { dateFormat: "Y-m-d", locale: "zh", disableMobile: true };
  fpStart = flatpickr("#r-start", { ...cfg, onChange: (_, s) => {
    if (!current) return;
    current.week_start = s; setDirty(true);
  }});
  fpEnd = flatpickr("#r-end", { ...cfg, onChange: (_, s) => {
    if (!current) return;
    current.week_end = s; setDirty(true);
  }});
}

$("#switch-mode").addEventListener("click", (e) => {
  e.preventDefault();
  registerMode = !registerMode;
  $("#login-title").textContent = registerMode ? "注册" : "登录";
  $("#login-hint").textContent = registerMode ? "创建一个新账号" : "使用你的账号继续";
  $("#login-submit").textContent = registerMode ? "注 册" : "登 录";
  $("#register-extra").classList.toggle("hidden", !registerMode);
  $("#switch-text").textContent = registerMode ? "已有账号?" : "还没有账号?";
  $("#switch-mode").textContent = registerMode ? "去登录" : "注册新账号";
  $("#login-error").textContent = "";
});

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  const body = {
    username: $("#f-username").value.trim(),
    password: $("#f-password").value,
  };
  try {
    if (registerMode) {
      body.display_name = $("#f-display").value.trim();
      body.email = $("#f-email").value.trim();
      await api("/api/register", { method: "POST", body: JSON.stringify(body) });
      // 注册后待管理员审核,不自动登录:切回登录态并提示
      $("#switch-mode").click();
      $("#f-password").value = "";
      $("#login-hint").textContent = "注册成功,待管理员审核通过后即可登录";
      toast("注册成功,请等待管理员审核");
      return;
    }
    me = await api("/api/login", { method: "POST", body: JSON.stringify(body) });
    await showApp();
    await refreshList(true);
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

$("#btn-logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  me = null; current = null;
  showLogin();
});

/* ---------------- 周报列表 ---------------- */
async function refreshList(openFirst = false) {
  reports = await api("/api/reports");
  const nav = $("#report-list");
  nav.innerHTML = "";
  for (const r of reports) {
    const btn = document.createElement("button");
    btn.className = "report-item" + (current && current.id === r.id ? " active" : "");
    const st = r.review_status || "draft";
    btn.innerHTML = `<span class="ri-top"><span class="ri-week">${fmtDot(r.week_start)} – ${fmtDot(r.week_end)}</span>
                     <span class="badge mini badge-${st}">${REVIEW_LABEL[st] || st}</span></span>
                     <span class="ri-date">更新于 ${r.updated_at.replace("T", " ")}</span>`;
    btn.addEventListener("click", () => openReport(r.id));
    nav.appendChild(btn);
  }
  if (openFirst && reports.length) await openReport(reports[0].id);
  if (!reports.length) {
    current = null;
    $("#empty-state").classList.remove("hidden");
    $("#report-canvas").classList.add("hidden");
  }
}

async function openReport(id) {
  if (dirty && current) await saveReport();
  if (editingTemplateId) leaveTemplateMode();
  current = await api(`/api/reports/${id}`);
  renderReport();
  refreshListActive();
}

function refreshListActive() {
  document.querySelectorAll(".report-item").forEach((el, i) => {
    el.classList.toggle("active", reports[i] && current && reports[i].id === current.id);
  });
}

/* ---------------- 新建周报:选择所属周 + 模板 ---------------- */
let fpNew = null;

// 由任意一天推算所属周的周一~周日(ISO,整周)
function weekRange(d) {
  const day = (d.getDay() + 6) % 7; // 周一=0
  const monday = new Date(d);
  monday.setDate(d.getDate() - day);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  const iso = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
  return { start: iso(monday), end: iso(sunday) };
}

function updateNewRange() {
  const sel = fpNew && fpNew.selectedDates[0];
  if (!sel) { $("#newreport-range").textContent = ""; return; }
  const { start, end } = weekRange(sel);
  $("#newreport-range").textContent = `将创建:${fmtDot(start)} – ${fmtDot(end)}`;
}

// 模态内的模板选择(下拉框);仅在用户有多个模板时显示
function renderNewTplPicker() {
  const wrap = $("#newreport-templates");
  const sel = $("#newreport-template-select");
  if (!wrap || !sel) return;
  if (templates.length <= 1) { wrap.classList.add("hidden"); return; }
  wrap.classList.remove("hidden");
  sel.innerHTML = "";
  for (const t of templates) {
    const opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = t.id === defaultTemplateId ? `${t.name}(默认)` : t.name;
    sel.appendChild(opt);
  }
  sel.value = defaultTemplateId; // 默认选中默认模板
}

function openNewReportModal() {
  if (!fpNew) {
    fpNew = flatpickr("#newreport-date", {
      dateFormat: "Y-m-d", locale: "zh", disableMobile: true,
      onChange: updateNewRange,
    });
  }
  fpNew.setDate(new Date(), false);
  updateNewRange();
  renderNewTplPicker();
  $("#newreport-modal").classList.remove("hidden");
}

function closeNewReportModal() {
  $("#newreport-modal").classList.add("hidden");
}

$("#btn-new-report").addEventListener("click", openNewReportModal);
$("#newreport-close").addEventListener("click", closeNewReportModal);
$("#newreport-modal").addEventListener("click", (e) => {
  if (e.target.id === "newreport-modal") closeNewReportModal();
});
$("#newreport-thisweek").addEventListener("click", () => {
  fpNew.setDate(new Date(), false);
  updateNewRange();
});

$("#newreport-create").addEventListener("click", async () => {
  const sel = fpNew && fpNew.selectedDates[0];
  if (!sel) { toast("请选择日期"); return; }
  const week_start = weekRange(sel).start;
  const templateId = templates.length > 1 ? $("#newreport-template-select").value : null;
  if (dirty && current) await saveReport();
  if (editingTemplateId) leaveTemplateMode();
  try {
    const q = templateId ? `?template_id=${encodeURIComponent(templateId)}` : "";
    current = await api("/api/reports" + q, { method: "POST", body: JSON.stringify({ week_start }) });
  } catch (e) {
    toast(e.message);
    return;
  }
  closeNewReportModal();
  await refreshList();
  renderReport();
  refreshListActive();
  toast("已创建周报");
});

$("#btn-delete-report").addEventListener("click", async () => {
  if (!current) return;
  if (!confirm("确定删除这份周报吗?此操作不可恢复。")) return;
  await api(`/api/reports/${current.id}`, { method: "DELETE" });
  current = null; dirty = false;
  await refreshList(true);
  toast("已删除");
});

/* ---------------- 编辑器渲染 ---------------- */
// 审核中/已通过的周报锁定为只读
function isLocked() {
  return !editingTemplateId && current &&
    ["pending", "approved", "reopen_pending"].includes(current.review_status);
}

function renderReport() {
  if (!current) return;
  $("#empty-state").classList.add("hidden");
  $("#report-canvas").classList.remove("hidden");
  $("#r-title").value = current.title;
  $("#r-greeting").value = current.greeting;
  $("#r-subtitle").value = current.subtitle;
  if (fpStart) fpStart.setDate(current.week_start, false);
  if (fpEnd) fpEnd.setDate(current.week_end, false);
  setDirty(false);

  const locked = isLocked();
  document.body.classList.toggle("report-locked", locked);
  $("#r-title").disabled = $("#r-greeting").disabled = $("#r-subtitle").disabled = locked;

  const host = $("#sections");
  host.innerHTML = "";
  current.sections.forEach((sec, si) => host.appendChild(renderSection(sec, si)));
  if (locked) {
    host.querySelectorAll("[contenteditable]").forEach((el) => (el.contentEditable = "false"));
    host.querySelectorAll("select.cell-select").forEach((el) => (el.disabled = true));
  }
  updateReviewUI();
}

function renderSection(sec, si) {
  const wrap = document.createElement("div");
  wrap.className = "section";

  // 区块标题栏 + 工具
  const bar = document.createElement("div");
  bar.className = "section-bar";
  const name = document.createElement("input");
  name.className = "section-name";
  name.value = sec.name;
  name.placeholder = "区块名称";
  name.addEventListener("input", () => { sec.name = name.value; setDirty(true); });
  bar.appendChild(name);

  const tools = document.createElement("div");
  tools.className = "section-tools no-export";
  tools.append(
    miniBtn("+ 列", () => {
      sec.columns.push({ key: "c_" + uid(), label: "新列", width: 160 });
      setDirty(true); rerenderSection(wrap, sec, si);
    }),
    miniBtn(sec.show_index ? "隐藏序号" : "显示序号", () => {
      sec.show_index = !sec.show_index;
      setDirty(true); rerenderSection(wrap, sec, si);
    }),
    miniBtn("删除区块", () => {
      if (!confirm(`删除区块「${sec.name}」?`)) return;
      current.sections.splice(si, 1);
      setDirty(true); renderReport();
    }, "danger"),
  );
  bar.appendChild(tools);
  wrap.appendChild(bar);

  // 表格
  const tblWrap = document.createElement("div");
  tblWrap.className = "tbl-wrap";
  const table = document.createElement("table");
  table.className = "wr";

  const thead = document.createElement("thead");
  const htr = document.createElement("tr");
  if (sec.show_index) {
    const th = document.createElement("th");
    th.className = "idx-col";
    th.innerHTML = '<span class="hcell" style="padding:8px 4px">No.</span>';
    htr.appendChild(th);
  }
  sec.columns.forEach((col, ci) => {
    const th = document.createElement("th");
    th.style.minWidth = (col.width || 120) + "px";
    const h = document.createElement("div");
    h.className = "hcell";
    h.contentEditable = "plaintext-only";
    h.textContent = col.label;
    h.addEventListener("input", () => { col.label = h.innerText.trim(); setDirty(true); });
    th.appendChild(h);
    // 列设置:文本列 / 绑定选项集变下拉列
    const gear = document.createElement("button");
    gear.className = "col-gear no-export";
    gear.textContent = "⚙";
    gear.title = "列设置(文本/下拉)";
    gear.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openColMenu(gear, col, () => rerenderSection(wrap, sec, si));
    });
    th.appendChild(gear);
    const x = document.createElement("button");
    x.className = "col-x no-export";
    x.textContent = "×";
    x.title = "删除此列";
    x.addEventListener("click", () => {
      if (!confirm(`删除列「${col.label}」及其数据?`)) return;
      sec.columns.splice(ci, 1);
      sec.rows.forEach((r) => delete r[col.key]);
      setDirty(true); rerenderSection(wrap, sec, si);
    });
    th.appendChild(x);
    htr.appendChild(th);
  });
  thead.appendChild(htr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  sec.rows.forEach((row, ri) => {
    const tr = document.createElement("tr");
    if (sec.show_index) {
      const td = document.createElement("td");
      td.className = "idx";
      td.textContent = ri + 1;
      tr.appendChild(td);
    }
    sec.columns.forEach((col, ci) => {
      const td = document.createElement("td");
      if (col.type === "select") {
        const sel = document.createElement("select");
        sel.className = "cell-select";
        const cur = row[col.key] || "";
        const opts = (optionSets[col.options] || []).slice();
        if (cur && !opts.includes(cur)) opts.unshift(cur); // 保留不在候选中的旧值
        sel.appendChild(new Option("— 请选择 —", ""));
        for (const o of opts) sel.appendChild(new Option(o, o));
        sel.value = cur;
        sel.classList.toggle("empty", !cur);
        sel.addEventListener("change", () => {
          row[col.key] = sel.value;
          sel.classList.toggle("empty", !sel.value);
          setDirty(true);
        });
        td.appendChild(sel);
      } else {
        const cell = document.createElement("div");
        cell.className = "cell";
        cell.contentEditable = "plaintext-only";
        cell.innerText = row[col.key] || "";
        cell.addEventListener("input", () => { row[col.key] = cell.innerText; setDirty(true); });
        td.appendChild(cell);
      }
      tr.appendChild(td);
    });
    // 行删除按钮挂在行内第一个单元格,悬停行时出现
    if (tr.firstChild) {
      const x = document.createElement("button");
      x.className = "row-x no-export";
      x.textContent = "×";
      x.title = "删除此行";
      x.addEventListener("click", () => {
        sec.rows.splice(ri, 1);
        setDirty(true); rerenderSection(wrap, sec, si);
      });
      tr.firstChild.style.overflow = "visible";
      tr.firstChild.appendChild(x);
    }
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  tblWrap.appendChild(table);
  wrap.appendChild(tblWrap);

  // 添加行
  const addRow = document.createElement("button");
  addRow.className = "row-add no-export";
  addRow.textContent = "+ 添加一行";
  addRow.addEventListener("click", () => {
    sec.rows.push({});
    setDirty(true); rerenderSection(wrap, sec, si);
  });
  wrap.appendChild(addRow);

  return wrap;
}

function rerenderSection(oldWrap, sec, si) {
  oldWrap.replaceWith(renderSection(sec, si));
}

$("#btn-add-section").addEventListener("click", () => {
  current.sections.push({
    id: uid(), name: "新区块", show_index: true,
    columns: [
      { key: "c_" + uid(), label: "项目", width: 200 },
      { key: "c_" + uid(), label: "内容", width: 400 },
    ],
    rows: [{}],
  });
  setDirty(true);
  renderReport();
});

// 顶部字段绑定(日期由 flatpickr 单独处理)
for (const [id, key] of [["r-title", "title"], ["r-greeting", "greeting"], ["r-subtitle", "subtitle"]]) {
  $("#" + id).addEventListener("input", (e) => {
    if (!current) return;
    current[key] = e.target.value;
    setDirty(true);
  });
}

/* ---------------- 保存 ---------------- */
async function saveReport() {
  if (!current) return;
  clearTimeout(saveTimer);
  if (editingTemplateId) {
    await api(`/api/templates/${editingTemplateId}`, {
      method: "PUT",
      body: JSON.stringify({
        name: editingTemplateName,
        title: current.title, greeting: current.greeting, subtitle: current.subtitle,
        sections: current.sections,
      }),
    });
    await loadTemplates();
    setDirty(false);
    return;
  }
  const body = {
    title: current.title, greeting: current.greeting, subtitle: current.subtitle,
    week_start: current.week_start, week_end: current.week_end,
    sections: current.sections,
  };
  const r = await api(`/api/reports/${current.id}`, { method: "PUT", body: JSON.stringify(body) });
  current.updated_at = r.updated_at;
  setDirty(false);
}

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "s") {
    e.preventDefault();
    saveReport().then(() => toast("已保存"));
  }
});
window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); } });

/* ---------------- 审批工作流 ---------------- */
const REVIEW_LABEL = {
  draft: "草稿", pending: "待审核", approved: "已通过", rejected: "已拒绝", reopen_pending: "修改待审",
};
const ACTION_LABEL = {
  submit: "提交审核", withdraw: "撤回提交", approve: "审核通过", reject: "审核拒绝",
  reopen_request: "申请修改", reopen_approve: "同意修改", reopen_reject: "驳回修改申请", reopen_cancel: "撤回修改申请",
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function lastReject() {
  if (!current) return null;
  const rejects = current.review_history.filter((e) => e.action === "reject");
  return rejects.length ? rejects[rejects.length - 1] : null;
}

// 根据当前周报的审核状态刷新工具栏徽章/按钮与提示条
function updateReviewUI() {
  const tpl = !!editingTemplateId;
  const st = current ? current.review_status : null;
  const has = (id) => $("#" + id);
  const show = (id, v) => has(id).classList.toggle("hidden", !v);

  // 模板编辑模式下隐藏全部审核控件
  if (tpl || !current) {
    ["review-badge", "btn-submit-review", "btn-withdraw", "btn-reopen", "btn-history"].forEach((i) => show(i, false));
    $("#review-bar").classList.add("hidden");
    return;
  }

  const badge = $("#review-badge");
  badge.textContent = REVIEW_LABEL[st] || st;
  badge.className = "badge badge-" + st;
  show("review-badge", true);

  show("btn-submit-review", st === "draft" || st === "rejected");
  $("#btn-submit-review").textContent = st === "rejected" ? "重新提交审核" : "提交审核";
  // 撤回:待审核 / 修改申请待审 都可撤回
  show("btn-withdraw", st === "pending" || st === "reopen_pending");
  $("#btn-withdraw").textContent = st === "reopen_pending" ? "撤回申请" : "撤回";
  // 已通过 → 申请修改(需管理员同意);修改待审时按钮隐藏(改走「撤回申请」)
  show("btn-reopen", st === "approved");
  show("btn-history", current.review_history.length > 0);

  // 提示条
  const bar = $("#review-bar");
  bar.className = "review-bar";
  if (st === "rejected") {
    const rj = lastReject();
    bar.classList.add("rejected");
    bar.innerHTML = `<span><b>审核被拒绝</b>${rj && rj.reason ? " · 理由:" + esc(rj.reason) : ""}。修改后可点工具栏「重新提交审核」。</span>`;
  } else if (st === "pending") {
    bar.classList.add("pending");
    bar.innerHTML = `<span>已提交,<b>等待管理员审核</b>。审核期间不可编辑,如需修改请先「撤回」。</span>`;
  } else if (st === "approved") {
    bar.classList.add("approved");
    bar.innerHTML = `<span><b>已通过审核</b>,周报已锁定。如需修改请点工具栏「申请修改」,<b>管理员同意后</b>方可再次编辑。</span>`;
  } else if (st === "reopen_pending") {
    bar.classList.add("pending");
    bar.innerHTML = `<span>已提交<b>修改申请</b>,等待管理员审批。期间周报仍锁定;可点「撤回申请」取消。</span>`;
  } else {
    bar.classList.add("hidden");
  }
}

async function doReviewAction(path, okMsg) {
  if (!current) return;
  if (dirty) await saveReport();
  try {
    current = await api(`/api/reports/${current.id}/${path}`, { method: "POST" });
    renderReport();
    await refreshList();
    refreshListActive();
    toast(okMsg);
  } catch (e) { toast(e.message); }
}

$("#btn-submit-review").addEventListener("click", () => doReviewAction("submit", "已提交审核"));
$("#btn-withdraw").addEventListener("click", () => {
  const msg = current && current.review_status === "reopen_pending" ? "已撤回修改申请" : "已撤回,可继续编辑";
  doReviewAction("withdraw", msg);
});
$("#btn-reopen").addEventListener("click", () => {
  if (!confirm("向管理员申请修改本周报?管理员同意后才能再次编辑。")) return;
  doReviewAction("request-reopen", "已提交修改申请,等待管理员审批");
});

/* ---- 审核历史弹窗 ---- */
$("#btn-history").addEventListener("click", openHistory);
$("#history-close").addEventListener("click", () => $("#history-modal").classList.add("hidden"));
$("#history-close2").addEventListener("click", () => $("#history-modal").classList.add("hidden"));

function openHistory() {
  if (!current) return;
  const body = $("#history-body");
  const evs = current.review_history.slice().reverse();
  if (!evs.length) { body.innerHTML = `<p class="hist-empty">暂无记录</p>`; }
  else {
    body.innerHTML = `<ul class="timeline">` + evs.map((e) => {
      const snap = e.action === "submit" && e.snapshot
        ? `<button class="mini-btn snap-btn" data-id="${e.id}">查看快照</button>` : "";
      const reason = e.reason ? `<div class="tl-reason">理由:${esc(e.reason)}</div>` : "";
      return `<li class="tl-item tl-${e.action}">
        <div class="tl-dot"></div>
        <div class="tl-body">
          <div class="tl-head"><b>${ACTION_LABEL[e.action] || e.action}</b>
            <span class="tl-actor">${esc(e.actor)}</span>
            <span class="tl-at">${(e.at || "").replace("T", " ")}</span>${snap}</div>
          ${reason}
        </div></li>`;
    }).join("") + `</ul>`;
    body.querySelectorAll(".snap-btn").forEach((b) => {
      b.addEventListener("click", () => {
        const ev = current.review_history.find((x) => x.id === b.dataset.id);
        if (ev && ev.snapshot) openSnapshot(ev);
      });
    });
  }
  $("#history-modal").classList.remove("hidden");
}

/* ---- 快照只读全屏 ---- */
$("#snap-close").addEventListener("click", () => $("#snap-modal").classList.add("hidden"));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("#snap-modal").classList.add("hidden");
});

function openSnapshot(ev) {
  $("#snap-title").textContent = `提交快照 · ${(ev.at || "").replace("T", " ")}`;
  $("#snap-view").innerHTML = renderSnapshotHTML(ev.snapshot);
  $("#snap-modal").classList.remove("hidden");
}

// 只读渲染一份内容快照(title/greeting/subtitle/sections)
function renderSnapshotHTML(snap) {
  let h = `<div class="ro-sheet"><div class="ro-title">${esc(snap.title)}</div>`;
  if (snap.greeting) h += `<div class="ro-greeting">${esc(snap.greeting)}</div>`;
  if (snap.subtitle) h += `<div class="ro-subtitle">${esc(snap.subtitle)}</div>`;
  for (const sec of snap.sections || []) {
    h += `<div class="ro-section-name">${esc(sec.name)}</div><div class="ro-table-scroll"><table class="ro-table"><thead><tr>`;
    if (sec.show_index) h += `<th class="ro-idx">No.</th>`;
    for (const col of sec.columns || []) h += `<th>${esc(col.label)}</th>`;
    h += `</tr></thead><tbody>`;
    const rows = sec.rows || [];
    if (!rows.length) {
      const span = (sec.columns || []).length + (sec.show_index ? 1 : 0);
      h += `<tr><td class="ro-empty" colspan="${span || 1}">(空)</td></tr>`;
    }
    rows.forEach((row, i) => {
      h += `<tr>`;
      if (sec.show_index) h += `<td class="ro-idx">${i + 1}</td>`;
      for (const col of sec.columns || []) h += `<td>${esc(row[col.key]).replace(/\n/g, "<br>")}</td>`;
      h += `</tr>`;
    });
    h += `</tbody></table></div>`;
  }
  return h + `</div>`;
}

/* ---------------- 存为模板 ---------------- */
// 把当前周报结构(标题中的日期反向替换为占位符)打包成模板正文
function currentAsTemplateBody() {
  const s = fmtDot(current.week_start), e = fmtDot(current.week_end);
  return {
    title: current.title.replaceAll(s, "{start}").replaceAll(e, "{end}"),
    greeting: current.greeting,
    subtitle: current.subtitle.replaceAll(s, "{start}").replaceAll(e, "{end}"),
    sections: current.sections.map((sec) => ({
      ...sec,
      rows: sec.rows.length ? sec.rows : [{}],
    })),
  };
}

$("#btn-save-template").addEventListener("click", async () => {
  if (!current) return;
  const name = (prompt("模板名称(同名将覆盖该模板):", "我的模板") || "").trim();
  if (!name) return;
  const body = { name, ...currentAsTemplateBody() };
  const existing = templates.find((t) => t.name === name);
  try {
    if (existing) {
      await api(`/api/templates/${existing.id}`, { method: "PUT", body: JSON.stringify(body) });
    } else {
      await api("/api/templates", { method: "POST", body: JSON.stringify(body) });
    }
  } catch (err) { toast(err.message); return; }
  await loadTemplates();
  toast(existing ? `已更新模板「${name}」` : `已存为模板「${name}」,新建周报时可选用`);
});

/* ---------------- 模板管理弹窗 ---------------- */
function renderTemplatesModal() {
  const body = $("#templates-body");
  body.innerHTML = "";
  for (const t of templates) {
    const box = document.createElement("div");
    box.className = "tpl-row";

    const nameInput = document.createElement("input");
    nameInput.className = "tpl-name";
    nameInput.value = t.name;
    nameInput.addEventListener("change", async () => {
      const nv = nameInput.value.trim();
      if (!nv || nv === t.name) { nameInput.value = t.name; return; }
      await api(`/api/templates/${t.id}`, { method: "PUT", body: JSON.stringify({
        name: nv, title: t.title, greeting: t.greeting, subtitle: t.subtitle, sections: t.sections,
      }) });
      await loadTemplates(); renderTemplatesModal();
      toast("已重命名");
    });
    box.appendChild(nameInput);

    const tools = document.createElement("div");
    tools.className = "tpl-row-tools";
    tools.appendChild(miniBtn("修改", () => enterTemplateEdit(t)));
    if (t.id === defaultTemplateId) {
      const badge = document.createElement("span");
      badge.className = "tpl-badge";
      badge.textContent = "默认";
      tools.appendChild(badge);
    } else {
      tools.appendChild(miniBtn("设为默认", async () => {
        await api(`/api/templates/${t.id}/default`, { method: "POST" });
        await loadTemplates(); renderTemplatesModal(); toast("已设为默认模板");
      }));
    }
    tools.appendChild(miniBtn("删除", async () => {
      if (!confirm(`删除模板「${t.name}」?`)) return;
      try { await api(`/api/templates/${t.id}`, { method: "DELETE" }); }
      catch (err) { toast(err.message); return; }
      await loadTemplates(); renderTemplatesModal(); toast("已删除");
    }, "danger"));
    box.appendChild(tools);
    body.appendChild(box);
  }
}

/* ---------------- 模板编辑模式 ----------------
   复用周报编辑器:把模板正文装进 current 当作"伪周报"编辑,
   editingTemplateId 非空时保存路由到 /api/templates 而非 /api/reports。 */
let editingTemplateId = null;
let editingTemplateName = "";

function enterTemplateEdit(t) {
  closeTemplatesModal();
  editingTemplateId = t.id;
  editingTemplateName = t.name;
  current = {
    id: t.id,
    title: t.title || "",
    greeting: t.greeting || "",
    subtitle: t.subtitle || "",
    week_start: "",
    week_end: "",
    sections: JSON.parse(JSON.stringify(t.sections || [])),
  };
  document.body.classList.add("tpl-editing");
  $("#tpl-edit-name").textContent = t.name;
  $("#tpl-edit-bar").classList.remove("hidden");
  renderReport();
  refreshListActive();
}

// 仅清理模板编辑模式的 UI/状态,不触发保存或列表刷新
function leaveTemplateMode() {
  editingTemplateId = null;
  document.body.classList.remove("tpl-editing");
  $("#tpl-edit-bar").classList.add("hidden");
}

async function exitTemplateEdit() {
  if (dirty && current) await saveReport(); // 模板模式下 saveReport 会写回模板
  leaveTemplateMode();
  current = null; dirty = false;
  await refreshList(true);
  toast("模板已保存");
}
$("#tpl-edit-done").addEventListener("click", exitTemplateEdit);

function closeTemplatesModal() { $("#templates-modal").classList.add("hidden"); }
$("#btn-templates").addEventListener("click", async () => {
  await loadTemplates();
  renderTemplatesModal();
  $("#templates-modal").classList.remove("hidden");
});
$("#templates-close").addEventListener("click", closeTemplatesModal);
$("#templates-close2").addEventListener("click", closeTemplatesModal);
$("#templates-modal").addEventListener("click", (e) => {
  if (e.target === $("#templates-modal")) closeTemplatesModal();
});

/* ---------------- 导出 ---------------- */
$("#btn-export-xlsx").addEventListener("click", async () => {
  if (!current) return;
  // 锁定状态(待审/已通过/修改待审)不能 PUT,跳过保存直接导出已存内容
  if (dirty && !isLocked()) await saveReport();
  window.location.href = `/api/reports/${current.id}/xlsx`;
});

/* ---------------- 邮件 ---------------- */
function esc(s) {
  return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br>");
}

function buildEmailHtml() {
  const td = 'border:1px solid #333;padding:6px 8px;vertical-align:top;font-size:13px;';
  const th = td + 'background:#d9d9d9;font-weight:bold;text-align:center;';
  let html = `<div style="font-family:'Microsoft YaHei',Arial,sans-serif;color:#1c2742;">`;
  html += `<p style="font-size:16px;font-weight:bold;">${esc(current.title)}</p>`;
  html += `<p>${esc(current.greeting)}</p>`;
  html += `<p style="font-weight:bold;">${esc(current.subtitle)}</p>`;
  for (const sec of current.sections) {
    if (sec.name) html += `<p style="font-size:14px;font-weight:bold;margin:14px 0 6px;">${esc(sec.name)}</p>`;
    html += `<table style="border-collapse:collapse;width:100%;"><tr>`;
    if (sec.show_index) html += `<th style="${th}width:40px;">No.</th>`;
    for (const c of sec.columns) html += `<th style="${th}">${esc(c.label)}</th>`;
    html += `</tr>`;
    sec.rows.forEach((row, i) => {
      html += `<tr>`;
      if (sec.show_index) html += `<td style="${td}text-align:center;">${i + 1}</td>`;
      for (const c of sec.columns) html += `<td style="${td}">${esc(row[c.key])}</td>`;
      html += `</tr>`;
    });
    html += `</table>`;
  }
  html += `</div>`;
  return html;
}

$("#btn-email").addEventListener("click", async () => {
  if (!current) return;
  await saveReport();
  const html = buildEmailHtml();
  try {
    // 以 text/html 写入剪贴板,粘贴到 Outlook 时保留表格格式
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([current.title], { type: "text/plain" }),
      }),
    ]);
    toast("周报已复制(带格式)。即将打开邮件,正文中 Ctrl+V 粘贴即可");
  } catch {
    toast("剪贴板写入失败,将仅打开邮件窗口");
  }
  const subject = encodeURIComponent(current.title);
  setTimeout(() => { window.location.href = `mailto:?subject=${subject}`; }, 600);
});

/* ---------------- 列设置浮层 ---------------- */
function openColMenu(anchor, col, onChange) {
  const menu = $("#col-menu");
  menu.innerHTML = "";
  const title = document.createElement("div");
  title.className = "cm-title";
  title.textContent = "列类型";
  menu.appendChild(title);

  const textBtn = document.createElement("button");
  textBtn.textContent = "文本输入";
  textBtn.className = col.type !== "select" ? "on" : "";
  textBtn.addEventListener("click", () => {
    col.type = "text"; col.options = "";
    setDirty(true); closeColMenu(); onChange();
  });
  menu.appendChild(textBtn);

  for (const name of Object.keys(optionSets)) {
    const b = document.createElement("button");
    b.textContent = `下拉:${name}`;
    if (col.type === "select" && col.options === name) b.className = "on";
    b.addEventListener("click", () => {
      col.type = "select"; col.options = name;
      setDirty(true); closeColMenu(); onChange();
    });
    menu.appendChild(b);
  }

  const r = anchor.getBoundingClientRect();
  menu.style.left = Math.min(r.left, window.innerWidth - 200) + "px";
  menu.style.top = (r.bottom + 4) + "px";
  menu.classList.remove("hidden");
}

function closeColMenu() { $("#col-menu").classList.add("hidden"); }
document.addEventListener("click", (e) => {
  if (!$("#col-menu").contains(e.target)) closeColMenu();
});

/* ---------------- 选项管理弹窗 ---------------- */
let editingSets = null; // 弹窗中的工作副本

function renderOptionsModal() {
  const body = $("#options-body");
  body.innerHTML = "";
  for (const [name, values] of Object.entries(editingSets)) {
    const box = document.createElement("div");
    box.className = "opt-set";

    const head = document.createElement("div");
    head.className = "opt-set-head";
    const nameInput = document.createElement("input");
    nameInput.className = "opt-set-name";
    nameInput.value = name;
    nameInput.addEventListener("change", () => {
      const nv = nameInput.value.trim();
      if (!nv || nv === name || editingSets[nv]) { nameInput.value = name; return; }
      const entries = Object.entries(editingSets).map(([k, v]) => [k === name ? nv : k, v]);
      editingSets = Object.fromEntries(entries);
      renderOptionsModal();
    });
    head.appendChild(nameInput);
    const del = document.createElement("button");
    del.className = "mini-btn danger opt-del";
    del.textContent = "删除选项集";
    del.addEventListener("click", () => {
      if (!confirm(`删除选项集「${name}」?绑定它的列会变回文本输入`)) return;
      delete editingSets[name];
      renderOptionsModal();
    });
    head.appendChild(del);
    box.appendChild(head);

    const chips = document.createElement("div");
    chips.className = "chips";
    values.forEach((v, i) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.append(v);
      const x = document.createElement("button");
      x.textContent = "×";
      x.addEventListener("click", () => { values.splice(i, 1); renderOptionsModal(); });
      chip.appendChild(x);
      chips.appendChild(chip);
    });
    const add = document.createElement("input");
    add.className = "chip-add";
    add.placeholder = "+ 回车添加";
    add.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const v = add.value.trim();
        if (v && !values.includes(v)) { values.push(v); renderOptionsModal(); }
        else add.value = "";
      }
    });
    chips.appendChild(add);
    box.appendChild(chips);
    body.appendChild(box);
  }
}

$("#btn-options").addEventListener("click", () => {
  editingSets = JSON.parse(JSON.stringify(optionSets));
  renderOptionsModal();
  $("#options-modal").classList.remove("hidden");
});
$("#options-close").addEventListener("click", () => $("#options-modal").classList.add("hidden"));
$("#options-modal").addEventListener("click", (e) => {
  if (e.target === $("#options-modal")) $("#options-modal").classList.add("hidden");
});
$("#newset-add").addEventListener("click", () => {
  const name = $("#newset-name").value.trim();
  if (!name || editingSets[name]) return;
  editingSets[name] = [];
  $("#newset-name").value = "";
  renderOptionsModal();
});
$("#options-save").addEventListener("click", async () => {
  optionSets = await api("/api/options", { method: "PUT", body: JSON.stringify({ option_sets: editingSets }) });
  $("#options-modal").classList.add("hidden");
  if (current) renderReport(); // 让下拉列立即用上新候选值
  toast("选项已保存");
});

/* ---------------- 导入历史周报 ---------------- */
$("#btn-import").addEventListener("click", () => $("#import-file").click());
$("#import-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch("/api/reports/import", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    current = await res.json();
    await refreshList();
    renderReport();
    refreshListActive();
    toast("导入成功,请检查并调整内容");
  } catch (err) {
    toast("导入失败:" + err.message);
  }
});

/* ---------------- 启动 ---------------- */
(async function init() {
  try {
    me = await api("/api/me");
    await showApp();
    await refreshList(true);
  } catch {
    showLogin();
  }
})();
