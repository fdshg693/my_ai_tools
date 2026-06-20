"use strict";

// memo ユーザー管理画面のロジック。/api/users の REST を叩いて一覧・追加・編集・削除する。

const ADMIN_USER = "admin"; // admin は削除不可 (サーバー側でもガードされる)

const rowsEl = document.getElementById("user-rows");
const emptyEl = document.getElementById("empty");
const toastEl = document.getElementById("toast");

function showToast(message, isError = false) {
  toastEl.textContent = message;
  toastEl.classList.toggle("error", isError);
  toastEl.hidden = false;
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => {
    toastEl.hidden = true;
  }, 2600);
}

// fetch ラッパー。エラー時は JSON の error メッセージを投げる。
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* ボディなし (204 等) は無視 */
  }
  if (!res.ok) {
    throw new Error((data && data.error) || `HTTP ${res.status}`);
  }
  return data;
}

function escapeHtml(s) {
  return String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

function renderRow(user) {
  const tr = document.createElement("tr");
  const isAdmin = user.name === ADMIN_USER;
  tr.dataset.name = user.name;
  tr.innerHTML = `
    <td>
      <span class="name">${escapeHtml(user.name)}</span>
      ${isAdmin ? '<span class="badge">特権</span>' : ""}
    </td>
    <td><input class="edit-display" value="${escapeHtml(user.display_name)}" placeholder="(なし)" /></td>
    <td><input class="edit-note" value="${escapeHtml(user.note)}" placeholder="(なし)" /></td>
    <td class="muted">${escapeHtml(user.created_at)}</td>
    <td class="actions">
      <button type="button" class="link save-btn">保存</button>
      ${isAdmin ? "" : '<button type="button" class="link danger delete-btn">削除</button>'}
    </td>
  `;

  tr.querySelector(".save-btn").addEventListener("click", async () => {
    const display_name = tr.querySelector(".edit-display").value;
    const note = tr.querySelector(".edit-note").value;
    try {
      await api(`/api/users/${encodeURIComponent(user.name)}`, {
        method: "PUT",
        body: JSON.stringify({ display_name, note }),
      });
      showToast(`「${user.name}」を更新しました`);
    } catch (e) {
      showToast(e.message, true);
    }
  });

  const deleteBtn = tr.querySelector(".delete-btn");
  if (deleteBtn) {
    deleteBtn.addEventListener("click", async () => {
      if (!confirm(`ユーザー「${user.name}」を削除しますか？\n(このユーザーのメモは残ります)`)) return;
      try {
        await api(`/api/users/${encodeURIComponent(user.name)}`, { method: "DELETE" });
        showToast(`「${user.name}」を削除しました`);
        loadUsers();
      } catch (e) {
        showToast(e.message, true);
      }
    });
  }

  return tr;
}

async function loadUsers() {
  try {
    const users = await api("/api/users");
    rowsEl.replaceChildren(...users.map(renderRow));
    emptyEl.hidden = users.length > 0;
  } catch (e) {
    showToast(e.message, true);
  }
}

document.getElementById("create-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const name = document.getElementById("new-name").value.trim();
  const display_name = document.getElementById("new-display").value.trim();
  const note = document.getElementById("new-note").value.trim();
  if (!name) {
    showToast("ユーザー名は必須です", true);
    return;
  }
  try {
    await api("/api/users", {
      method: "POST",
      body: JSON.stringify({ name, display_name, note }),
    });
    showToast(`「${name}」を追加しました`);
    ev.target.reset();
    loadUsers();
  } catch (e) {
    showToast(e.message, true);
  }
});

document.getElementById("reload").addEventListener("click", loadUsers);

loadUsers();
