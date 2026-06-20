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
      <button type="button" class="link memo-btn">メモ</button>
      <button type="button" class="link save-btn">保存</button>
      ${isAdmin ? "" : '<button type="button" class="link danger delete-btn">削除</button>'}
    </td>
  `;

  tr.querySelector(".memo-btn").addEventListener("click", () => openMemos(user.name));

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

// --- メモ一覧 (ユーザーごと・ページング) ------------------------------------

const PER_PAGE = 20;

const memoCard = document.getElementById("memo-card");
const memoUserEl = document.getElementById("memo-user");
const memoRowsEl = document.getElementById("memo-rows");
const memoEmptyEl = document.getElementById("memo-empty");
const memoPagerEl = document.getElementById("memo-pager");
const memoPageInfoEl = document.getElementById("memo-pageinfo");
const memoPrevBtn = document.getElementById("memo-prev");
const memoNextBtn = document.getElementById("memo-next");

// 現在表示中のメモ一覧の状態 (どのユーザーの何ページ目か)。
const memoView = { user: null, page: 1, totalPages: 0 };

function renderMemoRow(memo, user) {
  const tr = document.createElement("tr");
  tr.dataset.id = memo.id;
  tr.innerHTML = `
    <td class="muted">${memo.id}</td>
    <td>${escapeHtml(memo.title)}</td>
    <td class="summary">${escapeHtml(memo.summary)}</td>
    <td class="muted">${escapeHtml(memo.updated_at)}</td>
    <td class="actions">
      <button type="button" class="link edit-btn">編集</button>
      <button type="button" class="link danger delete-btn">削除</button>
    </td>
  `;

  // 編集はインラインでなく編集画面へ遷移する。
  tr.querySelector(".edit-btn").addEventListener("click", () => openMemoEditor(user, memo));

  tr.querySelector(".delete-btn").addEventListener("click", async () => {
    if (!confirm(`メモ #${memo.id}「${memo.title}」を削除しますか？`)) return;
    try {
      await api(`/api/users/${encodeURIComponent(user)}/memos/${memo.id}`, {
        method: "DELETE",
      });
      showToast(`メモ #${memo.id} を削除しました`);
      loadMemos(user, memoView.page);
    } catch (e) {
      showToast(e.message, true);
    }
  });

  return tr;
}

async function loadMemos(name, page) {
  try {
    const data = await api(
      `/api/users/${encodeURIComponent(name)}/memos?page=${page}&per_page=${PER_PAGE}`
    );
    memoView.user = name;
    memoView.page = data.page;
    memoView.totalPages = data.total_pages;

    memoUserEl.textContent = name;
    memoRowsEl.replaceChildren(...data.items.map((m) => renderMemoRow(m, name)));
    memoEmptyEl.hidden = data.total > 0;

    const hasPages = data.total_pages > 0;
    memoPagerEl.hidden = !hasPages;
    memoPageInfoEl.textContent = hasPages
      ? `${data.page} / ${data.total_pages} ページ (全 ${data.total} 件)`
      : "";
    memoPrevBtn.disabled = data.page <= 1;
    memoNextBtn.disabled = data.page >= data.total_pages;

    memoEditCard.hidden = true; // 一覧を表示するときは編集画面を畳む
    memoCard.hidden = false;
    memoCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    showToast(e.message, true);
  }
}

function openMemos(name) {
  loadMemos(name, 1);
}

memoPrevBtn.addEventListener("click", () => {
  if (memoView.page > 1) loadMemos(memoView.user, memoView.page - 1);
});
memoNextBtn.addEventListener("click", () => {
  if (memoView.page < memoView.totalPages) loadMemos(memoView.user, memoView.page + 1);
});
document.getElementById("memo-close").addEventListener("click", () => {
  memoCard.hidden = true;
  memoView.user = null;
});

// --- メモ編集画面 (新規作成 / 編集を 1 画面で兼ねる) -------------------------

const memoEditCard = document.getElementById("memo-edit-card");
const memoEditHeadingEl = document.getElementById("memo-edit-heading");
const memoEditForm = document.getElementById("memo-edit-form");
const editTitleEl = document.getElementById("edit-memo-title");
const editSummaryEl = document.getElementById("edit-memo-summary");

// 編集対象の状態。id が null なら新規作成、数値なら既存メモの更新。
const memoEdit = { user: null, id: null };

// memo を渡すと編集モード、省略すると新規作成モードで編集画面に遷移する。
function openMemoEditor(user, memo = null) {
  memoEdit.user = user;
  memoEdit.id = memo ? memo.id : null;
  memoEditHeadingEl.textContent = memo
    ? `「${user}」のメモを編集 (#${memo.id})`
    : `「${user}」に新しいメモを追加`;
  editTitleEl.value = memo ? memo.title : "";
  editSummaryEl.value = memo ? memo.summary : "";

  memoCard.hidden = true;
  memoEditCard.hidden = false;
  memoEditCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  editTitleEl.focus();
}

// 編集画面を閉じて一覧に戻る (保存はしない)。reload=true なら一覧を取り直す。
function closeMemoEditor(reload = false, page = memoView.page) {
  memoEditCard.hidden = true;
  if (reload) {
    loadMemos(memoEdit.user, page);
  } else {
    memoCard.hidden = false;
    memoCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  memoEdit.user = null;
  memoEdit.id = null;
}

document.getElementById("memo-new").addEventListener("click", () => {
  if (memoView.user) openMemoEditor(memoView.user);
});
document.getElementById("memo-edit-back").addEventListener("click", () => closeMemoEditor());
document.getElementById("memo-edit-cancel").addEventListener("click", () => closeMemoEditor());

memoEditForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (!memoEdit.user) return;
  const title = editTitleEl.value.trim();
  const summary = editSummaryEl.value;
  if (!title) {
    showToast("タイトルは必須です", true);
    return;
  }
  const isNew = memoEdit.id === null;
  const path = isNew
    ? `/api/users/${encodeURIComponent(memoEdit.user)}/memos`
    : `/api/users/${encodeURIComponent(memoEdit.user)}/memos/${memoEdit.id}`;
  try {
    await api(path, {
      method: isNew ? "POST" : "PUT",
      body: JSON.stringify({ title, summary }),
    });
    showToast(isNew ? "メモを追加しました" : `メモ #${memoEdit.id} を更新しました`);
    // 新規は更新日時が最新 → 1ページ目の先頭。編集は元のページに戻る。
    closeMemoEditor(true, isNew ? 1 : memoView.page);
  } catch (e) {
    showToast(e.message, true);
  }
});

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
