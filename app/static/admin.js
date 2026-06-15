/* 周报系统 · 管理后台:管理员登录、用户管理(审核/增删/改密)、只读查看周报 */
"use strict";

const $ = (sel) => document.querySelector(sel);

let admin = null;       // 当前管理员
let users = [];         // 普通用户列表

/* ---------------- API / 工具 ---------------- */
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove("show"), 2400);
}

function fmtDot(iso) { return (iso || "").replaceAll("-", "."); }
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

const STATUS_LABEL = { pending: "待审核", approved: "已通过", rejected: "已拒绝" };
const REVIEW_LABEL = {
  draft: "草稿", pending: "待审核", approved: "已通过", rejected: "已拒绝", reopen_pending: "修改待审",
};
const ACTION_LABEL = {
  submit: "提交审核", withdraw: "撤回提交", approve: "审核通过", reject: "审核拒绝",
  reopen_request: "申请修改", reopen_approve: "同意修改", reopen_reject: "驳回修改申请", reopen_cancel: "撤回修改申请",
};

let pending = [];  // 待审批周报队列

/* ---------------- 视图切换 ---------------- */
function showLogin() {
  $("#view-login").classList.remove("hidden");
  $("#view-admin").classList.add("hidden");
}
function showAdmin() {
  $("#view-login").classList.add("hidden");
  $("#view-admin").classList.remove("hidden");
  $("#admin-who").textContent = admin.display_name || admin.username;
}

/* ---------------- 登录 / 退出 ---------------- */
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    admin = await api("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ username: $("#f-username").value.trim(), password: $("#f-password").value }),
    });
    showAdmin();
    await refreshAll();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

$("#btn-logout").addEventListener("click", async () => {
  await api("/api/admin/logout", { method: "POST" });
  admin = null;
  showLogin();
});

async function refreshAll() {
  await Promise.all([loadPending(), loadUsers()]);
}

/* ---------------- 用户列表 ---------------- */
async function loadUsers() {
  users = await api("/api/admin/users");
  // 待审核置顶,其余按注册时间倒序
  users.sort((a, b) => {
    if ((a.status === "pending") !== (b.status === "pending")) return a.status === "pending" ? -1 : 1;
    return (b.created_at || "").localeCompare(a.created_at || "");
  });
  renderUsers();
}

function renderUsers() {
  const tbody = $("#users-body");
  tbody.innerHTML = "";
  const pending = users.filter((u) => u.status === "pending").length;
  $("#user-count").textContent = `共 ${users.length} 人${pending ? ` · ${pending} 待审核` : ""}`;
  $("#users-empty").classList.toggle("hidden", users.length > 0);

  for (const u of users) {
    const tr = document.createElement("tr");
    if (u.status === "pending") tr.className = "row-pending";
    tr.innerHTML = `
      <td class="c-user">${esc(u.username)}</td>
      <td>${esc(u.display_name)}</td>
      <td class="c-email">${esc(u.email) || "—"}</td>
      <td><span class="badge badge-${u.status}">${STATUS_LABEL[u.status] || u.status}</span></td>
      <td class="c-date">${(u.created_at || "").replace("T", " ")}</td>
      <td class="num">${u.report_count}</td>
      <td class="ops"><div class="ops-wrap"></div></td>`;
    const ops = tr.querySelector(".ops-wrap");
    if (u.status === "pending") {
      ops.appendChild(opBtn("通过", () => approve(u), "ok"));
      ops.appendChild(opBtn("拒绝", () => reject(u), "danger"));
    } else if (u.status === "rejected") {
      ops.appendChild(opBtn("恢复", () => approve(u), "ok"));
    }
    ops.appendChild(opBtn("查看周报", () => openReports(u)));
    ops.appendChild(opBtn("重置密码", () => openReset(u)));
    ops.appendChild(opBtn("删除", () => delUser(u), "danger"));
    tbody.appendChild(tr);
  }
}

function opBtn(text, onClick, kind = "") {
  const b = document.createElement("button");
  b.className = "op-btn" + (kind ? " " + kind : "");
  b.textContent = text;
  b.addEventListener("click", onClick);
  return b;
}

/* ---------------- 用户操作 ---------------- */
async function approve(u) {
  try { await api(`/api/admin/users/${u.id}/approve`, { method: "POST" }); toast("已通过"); await loadUsers(); }
  catch (e) { toast(e.message); }
}
async function reject(u) {
  if (!confirm(`确定拒绝「${u.username}」的注册申请?`)) return;
  try { await api(`/api/admin/users/${u.id}/reject`, { method: "POST" }); toast("已拒绝"); await loadUsers(); }
  catch (e) { toast(e.message); }
}
async function delUser(u) {
  if (!confirm(`确定删除「${u.username}」?其全部周报将一并删除,不可恢复。`)) return;
  try { await api(`/api/admin/users/${u.id}`, { method: "DELETE" }); toast("已删除"); await refreshAll(); }
  catch (e) { toast(e.message); }
}

/* ---------------- 添加用户 ---------------- */
function openModal(id) { $(id).classList.remove("hidden"); }
function closeModal(id) { $(id).classList.add("hidden"); }

$("#btn-add-user").addEventListener("click", () => {
  ["au-username", "au-password", "au-display", "au-email"].forEach((i) => ($("#" + i).value = ""));
  $("#adduser-error").textContent = "";
  openModal("#adduser-modal");
});
$("#adduser-close").addEventListener("click", () => closeModal("#adduser-modal"));
$("#adduser-save").addEventListener("click", async () => {
  $("#adduser-error").textContent = "";
  const body = {
    username: $("#au-username").value.trim(),
    password: $("#au-password").value,
    display_name: $("#au-display").value.trim(),
    email: $("#au-email").value.trim(),
  };
  if (body.username.length < 2 || body.password.length < 4) {
    $("#adduser-error").textContent = "用户名至少 2 位,密码至少 4 位";
    return;
  }
  try {
    await api("/api/admin/users", { method: "POST", body: JSON.stringify(body) });
    closeModal("#adduser-modal");
    toast("已创建");
    await loadUsers();
  } catch (e) { $("#adduser-error").textContent = e.message; }
});

/* ---------------- 修改我的密码 ---------------- */
$("#btn-change-pwd").addEventListener("click", () => {
  $("#pw-old").value = ""; $("#pw-new").value = ""; $("#pwd-error").textContent = "";
  openModal("#pwd-modal");
});
$("#pwd-close").addEventListener("click", () => closeModal("#pwd-modal"));
$("#pwd-save").addEventListener("click", async () => {
  $("#pwd-error").textContent = "";
  const old_password = $("#pw-old").value, new_password = $("#pw-new").value;
  if (new_password.length < 4) { $("#pwd-error").textContent = "新密码至少 4 位"; return; }
  try {
    await api("/api/admin/password", { method: "POST", body: JSON.stringify({ old_password, new_password }) });
    closeModal("#pwd-modal");
    toast("密码已修改");
  } catch (e) { $("#pwd-error").textContent = e.message; }
});

/* ---------------- 重置某用户密码 ---------------- */
let resetTarget = null;
function openReset(u) {
  resetTarget = u;
  $("#reset-name").textContent = u.username;
  $("#reset-new").value = ""; $("#reset-error").textContent = "";
  openModal("#reset-modal");
}
$("#reset-close").addEventListener("click", () => closeModal("#reset-modal"));
$("#reset-save").addEventListener("click", async () => {
  $("#reset-error").textContent = "";
  const new_password = $("#reset-new").value;
  if (new_password.length < 4) { $("#reset-error").textContent = "密码至少 4 位"; return; }
  try {
    await api(`/api/admin/users/${resetTarget.id}/password`, { method: "POST", body: JSON.stringify({ new_password }) });
    closeModal("#reset-modal");
    toast("密码已重置");
  } catch (e) { $("#reset-error").textContent = e.message; }
});

/* ---------------- 待审批周报 ---------------- */
async function loadPending() {
  pending = await api("/api/admin/reports/pending");
  renderPending();
}

function renderPending() {
  $("#pending-panel").classList.toggle("hidden", pending.length === 0);
  $("#pending-count").textContent = `${pending.length} 份待审`;
  const tbody = $("#pending-body");
  tbody.innerHTML = "";
  $("#pending-all").checked = false;
  for (const p of pending) {
    const isReopen = p.kind === "reopen";
    const kindTag = isReopen
      ? `<span class="badge mini badge-reopen_pending">修改申请</span>`
      : `<span class="badge mini badge-pending">新提交</span>`;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="chk"><input type="checkbox" class="pchk" value="${p.id}"></td>
      <td class="c-user">${esc(p.display_name || p.username)} <span class="c-sub">@${esc(p.username)}</span></td>
      <td>${kindTag} ${fmtDot(p.week_start)} – ${fmtDot(p.week_end)}</td>
      <td class="c-date">${(p.submitted_at || "").replace("T", " ")}</td>
      <td class="ops"><div class="ops-wrap"></div></td>`;
    const ops = tr.querySelector(".ops-wrap");
    ops.appendChild(opBtn("查看", () => viewPending(p)));
    ops.appendChild(opBtn(isReopen ? "同意" : "通过", () => reviewOne(p.id, "approve"), "ok"));
    ops.appendChild(opBtn(isReopen ? "驳回" : "拒绝", () => reviewOne(p.id, "reject"), "danger"));
    tbody.appendChild(tr);
  }
}

$("#pending-all").addEventListener("change", (e) => {
  document.querySelectorAll(".pchk").forEach((c) => (c.checked = e.target.checked));
});
$("#batch-approve").addEventListener("click", () => batchReview("approve"));
$("#batch-reject").addEventListener("click", () => batchReview("reject"));

function selectedPendingIds() {
  return [...document.querySelectorAll(".pchk:checked")].map((c) => c.value);
}

async function viewPending(p) {
  await openReports({ id: p.user_id, username: p.username });
  await showReport(p.id);
}

// 审批理由弹窗(通过/拒绝共用,理由可选)
let reviewConfirmCb = null;
function askReason(title, sub, onConfirm) {
  $("#review-title").textContent = title;
  $("#review-sub").textContent = sub;
  $("#review-reason").value = "";
  reviewConfirmCb = onConfirm;
  openModal("#review-modal");
}
$("#review-close").addEventListener("click", () => closeModal("#review-modal"));
$("#review-confirm").addEventListener("click", async () => {
  const reason = $("#review-reason").value.trim();
  const cb = reviewConfirmCb;
  reviewConfirmCb = null;
  closeModal("#review-modal");
  if (cb) await cb(reason);
});

function promptReview(action, onConfirm) {
  askReason(
    action === "approve" ? "通过周报" : "拒绝周报",
    action === "approve" ? "可选填通过备注,用户可在审核历史中看到" : "建议填写拒绝理由,用户将看到并据此修改",
    onConfirm,
  );
}

function reviewOne(rid, action) {
  promptReview(action, async (reason) => {
    try {
      await api(`/api/admin/reports/${rid}/${action}`, { method: "POST", body: JSON.stringify({ reason }) });
      toast(action === "approve" ? "已通过" : "已拒绝");
      await refreshAll();
      if (currentRep && currentRep.id === rid && !$("#reports-modal").classList.contains("hidden")) {
        await showReport(rid);
      }
    } catch (e) { toast(e.message); }
  });
}

function batchReview(action) {
  const ids = selectedPendingIds();
  if (!ids.length) { toast("请先勾选待审周报"); return; }
  promptReview(action, async (reason) => {
    try {
      const r = await api("/api/admin/reports/review", {
        method: "POST", body: JSON.stringify({ ids, action, reason }),
      });
      toast(`完成 ${r.done.length} 份${r.skipped.length ? `,跳过 ${r.skipped.length}` : ""}`);
      await refreshAll();
    } catch (e) { toast(e.message); }
  });
}

/* ---------------- 查看用户周报(只读) ---------------- */
async function openReports(u) {
  $("#reports-name").textContent = u.username;
  $("#reports-side").innerHTML = "";
  $("#reports-view").innerHTML = `<p class="admin-empty">加载中…</p>`;
  openModal("#reports-modal");
  let list = [];
  try { list = await api(`/api/admin/users/${u.id}/reports`); }
  catch (e) { $("#reports-view").innerHTML = `<p class="admin-empty">${esc(e.message)}</p>`; return; }
  if (!list.length) {
    $("#reports-view").innerHTML = `<p class="admin-empty">该用户暂无周报</p>`;
    return;
  }
  $("#reports-view").innerHTML = `<p class="admin-empty">选择左侧周报查看</p>`;
  for (const r of list) {
    const b = document.createElement("button");
    b.className = "rep-item";
    const st = r.review_status || "draft";
    b.innerHTML = `<span class="ri-top"><span class="ri-week">${fmtDot(r.week_start)} – ${fmtDot(r.week_end)}</span>
                   <span class="badge mini badge-${st}">${REVIEW_LABEL[st] || st}</span></span>
                   <span class="ri-date">更新于 ${(r.updated_at || "").replace("T", " ")}</span>`;
    b.addEventListener("click", async () => {
      document.querySelectorAll(".rep-item").forEach((el) => el.classList.remove("active"));
      b.classList.add("active");
      await showReport(r.id);
    });
    $("#reports-side").appendChild(b);
  }
}
$("#reports-close").addEventListener("click", () => closeModal("#reports-modal"));

let currentRep = null;  // 右侧/全屏当前显示的周报

async function showReport(rid) {
  $("#reports-view").innerHTML = `<p class="admin-empty">加载中…</p>`;
  let rep;
  try { rep = await api(`/api/admin/reports/${rid}`); }
  catch (e) { $("#reports-view").innerHTML = `<p class="admin-empty">${esc(e.message)}</p>`; return; }
  currentRep = rep;
  const st = rep.review_status || "draft";
  const isReopen = st === "reopen_pending";
  const canReview = st === "pending" || isReopen;
  let head = `<div class="ro-toolbar">
    <span class="badge badge-${st}">${REVIEW_LABEL[st] || st}</span>
    <button class="op-btn" id="fs-open">⛶ 全屏查看</button>`;
  if (canReview) {
    head += `<button class="op-btn ok" id="rv-approve">${isReopen ? "同意修改" : "通过"}</button>
             <button class="op-btn danger" id="rv-reject">${isReopen ? "驳回" : "拒绝"}</button>`;
  }
  head += `</div>`;
  $("#reports-view").innerHTML = head + renderReviewHistory(rep) + renderReportHTML(rep);
  $("#fs-open").addEventListener("click", openFullscreen);
  if (canReview) {
    $("#rv-approve").addEventListener("click", () => reviewOne(rep.id, "approve"));
    $("#rv-reject").addEventListener("click", () => reviewOne(rep.id, "reject"));
  }
  $("#reports-view").querySelectorAll(".snap-btn").forEach((b) => {
    b.addEventListener("click", () => {
      const ev = (currentRep.review_history || []).find((x) => x.id === b.dataset.id);
      if (ev && ev.snapshot) openSnapshotFs(ev);
    });
  });
}

// 审核历史时间线
function renderReviewHistory(rep) {
  const evs = (rep.review_history || []).slice().reverse();
  if (!evs.length) return "";
  let h = `<div class="ro-history"><div class="roh-title">审核历史</div><ul class="timeline">`;
  for (const e of evs) {
    const snap = e.action === "submit" && e.snapshot
      ? `<button class="mini-btn snap-btn" data-id="${e.id}">查看快照</button>` : "";
    const reason = e.reason ? `<div class="tl-reason">理由:${esc(e.reason)}</div>` : "";
    h += `<li class="tl-item tl-${e.action}"><div class="tl-dot"></div><div class="tl-body">
      <div class="tl-head"><b>${ACTION_LABEL[e.action] || e.action}</b>
        <span class="tl-actor">${esc(e.actor)}</span>
        <span class="tl-at">${(e.at || "").replace("T", " ")}</span>${snap}</div>${reason}</div></li>`;
  }
  return h + `</ul></div>`;
}

function openSnapshotFs(ev) {
  $("#fs-title").textContent = `提交快照 · ${(ev.at || "").replace("T", " ")}`;
  $("#fs-view").innerHTML = renderReportHTML(ev.snapshot);
  $("#fs-modal").classList.remove("hidden");
}

/* ---------------- 全屏查看单个周报 ---------------- */
function openFullscreen() {
  if (!currentRep) return;
  $("#fs-title").textContent = `${fmtDot(currentRep.week_start)} – ${fmtDot(currentRep.week_end)}`;
  $("#fs-view").innerHTML = renderReportHTML(currentRep);
  $("#fs-modal").classList.remove("hidden");
}
$("#fs-close").addEventListener("click", () => $("#fs-modal").classList.add("hidden"));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("#fs-modal").classList.add("hidden");
});

// 轻量只读渲染:遍历 sections→columns→rows
function renderReportHTML(rep) {
  // 顶部三字段为已净化富文本,直接输出 HTML(不再 esc)
  let h = `<div class="ro-sheet"><div class="ro-title">${rep.title || ""}</div>`;
  if (rep.greeting) h += `<div class="ro-greeting">${rep.greeting}</div>`;
  if (rep.subtitle) h += `<div class="ro-subtitle">${rep.subtitle}</div>`;
  for (const sec of rep.sections || []) {
    h += `<div class="ro-section-name">${esc(sec.name)}</div>`;
    h += `<div class="ro-table-scroll"><table class="ro-table"><thead><tr>`;
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
  h += `</div>`;
  return h;
}

// 点遮罩空白处关闭弹窗
document.querySelectorAll(".modal-mask").forEach((m) => {
  m.addEventListener("click", (e) => { if (e.target === m) m.classList.add("hidden"); });
});

/* ---------------- 启动 ---------------- */
(async function init() {
  try {
    admin = await api("/api/admin/me");
    showAdmin();
    await refreshAll();
  } catch {
    showLogin();
  }
})();
