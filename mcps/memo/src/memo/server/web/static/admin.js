"use strict";

// memo ユーザー管理画面のロジック。/api/users の REST を叩いて一覧・追加・編集・削除する。
//
// 管理者かどうかは名前ではなく user.is_admin フラグで判定する。is_admin の編集は
// この Web UI だけが行える (MCP ツールでは変更しない)。最後の1人の管理者は
// 削除/降格できない (サーバー側でガードし 403/409 を返す)。

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
  const isAdmin = !!user.is_admin;
  tr.dataset.name = user.name;
  tr.innerHTML = `
    <td>
      <span class="name">${escapeHtml(user.name)}</span>
      ${isAdmin ? '<span class="badge">管理者</span>' : ""}
    </td>
    <td><input class="edit-display" value="${escapeHtml(user.display_name)}" placeholder="(なし)" /></td>
    <td><input class="edit-note" value="${escapeHtml(user.note)}" placeholder="(なし)" /></td>
    <td class="admin-cell"><input type="checkbox" class="edit-admin"${isAdmin ? " checked" : ""} /></td>
    <td class="muted">${escapeHtml(user.created_at)}</td>
    <td class="actions">
      <button type="button" class="link memo-btn">メモ</button>
      <button type="button" class="link save-btn">保存</button>
      <button type="button" class="link danger delete-btn">削除</button>
    </td>
  `;

  tr.querySelector(".memo-btn").addEventListener("click", () => openMemos(user.name));

  tr.querySelector(".save-btn").addEventListener("click", async () => {
    const display_name = tr.querySelector(".edit-display").value;
    const note = tr.querySelector(".edit-note").value;
    const is_admin = tr.querySelector(".edit-admin").checked;
    try {
      await api(`/api/users/${encodeURIComponent(user.name)}`, {
        method: "PUT",
        body: JSON.stringify({ display_name, note, is_admin }),
      });
      showToast(`「${user.name}」を更新しました`);
      loadUsers();
    } catch (e) {
      showToast(e.message, true);
    }
  });

  tr.querySelector(".delete-btn").addEventListener("click", async () => {
    if (!confirm(`ユーザー「${user.name}」を削除しますか？\n(このユーザーのメモも一緒に削除されます)`)) return;
    try {
      await api(`/api/users/${encodeURIComponent(user.name)}`, { method: "DELETE" });
      showToast(`「${user.name}」を削除しました`);
      loadUsers();
    } catch (e) {
      showToast(e.message, true);
    }
  });

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
const memoFilterCategoryEl = document.getElementById("memo-filter-category");

// 現在表示中のメモ一覧の状態 (どのユーザーの何ページ目か・カテゴリ絞り込み)。
const memoView = { user: null, page: 1, totalPages: 0, category: "" };

// 現在開いているユーザーのカテゴリ名一覧 (select の選択肢に使う)。
let memoCategories = [];

// 指定ユーザーのカテゴリ名一覧を取得して memoCategories に保持する。
async function loadCategories(name) {
  const cats = await api(`/api/users/${encodeURIComponent(name)}/categories`);
  memoCategories = cats.map((c) => c.name);
  return memoCategories;
}

// select 要素にカテゴリ選択肢を流し込む。
// includeAll=true なら先頭に「(全カテゴリ)」(value="") を足す。
// selected を含まない名前なら防御的に末尾へ追加して選択状態にする。
function fillCategoryOptions(selectEl, { includeAll = false, selected = "" } = {}) {
  const names = [...memoCategories];
  if (selected && !names.includes(selected)) names.push(selected);
  const opts = [];
  if (includeAll) opts.push('<option value="">(全カテゴリ)</option>');
  for (const n of names) {
    const sel = n === selected ? " selected" : "";
    opts.push(`<option value="${escapeHtml(n)}"${sel}>${escapeHtml(n)}</option>`);
  }
  selectEl.innerHTML = opts.join("");
}

function renderMemoRow(memo, user) {
  const tr = document.createElement("tr");
  tr.dataset.id = memo.id;
  tr.innerHTML = `
    <td class="muted">${memo.id}</td>
    <td>${escapeHtml(memo.title)}</td>
    <td><span class="cat-badge">${escapeHtml(memo.category)}</span></td>
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

async function loadMemos(name, page, category = memoView.category) {
  try {
    let path = `/api/users/${encodeURIComponent(name)}/memos?page=${page}&per_page=${PER_PAGE}`;
    if (category) path += `&category=${encodeURIComponent(category)}`;
    const data = await api(path);
    memoView.user = name;
    memoView.page = data.page;
    memoView.totalPages = data.total_pages;
    memoView.category = category;

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

async function openMemos(name) {
  // ユーザーを開き直すときはカテゴリを読み直し、絞り込みをリセットする。
  try {
    await loadCategories(name);
  } catch (e) {
    showToast(e.message, true);
    return;
  }
  fillCategoryOptions(memoFilterCategoryEl, { includeAll: true, selected: "" });
  loadMemos(name, 1, "");
}

memoPrevBtn.addEventListener("click", () => {
  if (memoView.page > 1) loadMemos(memoView.user, memoView.page - 1);
});
memoNextBtn.addEventListener("click", () => {
  if (memoView.page < memoView.totalPages) loadMemos(memoView.user, memoView.page + 1);
});

// カテゴリ絞り込み: select の選択で 1 ページ目から取り直す (空 = 全カテゴリ)。
memoFilterCategoryEl.addEventListener("change", () => {
  if (!memoView.user) return;
  loadMemos(memoView.user, 1, memoFilterCategoryEl.value);
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
const editCategoryEl = document.getElementById("edit-memo-category");
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
  // カテゴリは登録済みから選ぶ。新規は OTHERS を既定選択。
  fillCategoryOptions(editCategoryEl, { selected: memo ? memo.category : "OTHERS" });
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
  const category = editCategoryEl.value; // 登録済みカテゴリから選択 (select)
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
      body: JSON.stringify({ title, summary, category }),
    });
    showToast(isNew ? "メモを追加しました" : `メモ #${memoEdit.id} を更新しました`);
    // 新規は更新日時が最新 → 1ページ目の先頭。編集は元のページに戻る。
    closeMemoEditor(true, isNew ? 1 : memoView.page);
  } catch (e) {
    showToast(e.message, true);
  }
});

// --- カテゴリ管理画面 (ユーザーごと) ----------------------------------------

const OTHERS_CATEGORY = "OTHERS"; // 既定カテゴリ。リネーム/削除不可 (サーバーもガード)

const categoryCard = document.getElementById("category-card");
const categoryUserEl = document.getElementById("category-user");
const categoryRowsEl = document.getElementById("category-rows");
const categoryEmptyEl = document.getElementById("category-empty");
const categoryCreateForm = document.getElementById("category-create-form");
const newCategoryEl = document.getElementById("new-category");

const categoryView = { user: null };

function renderCategoryRow(cat, user) {
  const tr = document.createElement("tr");
  const isOthers = cat.name === OTHERS_CATEGORY;
  tr.dataset.id = cat.id;
  tr.innerHTML = `
    <td>
      ${
        isOthers
          ? `<span class="name">${escapeHtml(cat.name)}</span> <span class="badge">既定</span>`
          : `<input class="edit-category-name" value="${escapeHtml(cat.name)}" />`
      }
    </td>
    <td class="actions">
      ${
        isOthers
          ? ""
          : '<button type="button" class="link save-btn">保存</button>' +
            '<button type="button" class="link danger delete-btn">削除</button>'
      }
    </td>
  `;

  const saveBtn = tr.querySelector(".save-btn");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const name = tr.querySelector(".edit-category-name").value.trim();
      if (!name) {
        showToast("カテゴリ名は必須です", true);
        return;
      }
      try {
        await api(`/api/users/${encodeURIComponent(user)}/categories/${cat.id}`, {
          method: "PUT",
          body: JSON.stringify({ name }),
        });
        showToast(`カテゴリを「${name}」に変更しました (メモも追従)`);
        loadCategoryRows(user);
      } catch (e) {
        showToast(e.message, true);
      }
    });
  }

  const deleteBtn = tr.querySelector(".delete-btn");
  if (deleteBtn) {
    deleteBtn.addEventListener("click", async () => {
      if (!confirm(`カテゴリ「${cat.name}」を削除しますか？\n(紐づくメモは ${OTHERS_CATEGORY} に移ります)`))
        return;
      try {
        await api(`/api/users/${encodeURIComponent(user)}/categories/${cat.id}`, {
          method: "DELETE",
        });
        showToast(`カテゴリ「${cat.name}」を削除しました`);
        loadCategoryRows(user);
      } catch (e) {
        showToast(e.message, true);
      }
    });
  }

  return tr;
}

async function loadCategoryRows(user) {
  try {
    const cats = await api(`/api/users/${encodeURIComponent(user)}/categories`);
    categoryRowsEl.replaceChildren(...cats.map((c) => renderCategoryRow(c, user)));
    categoryEmptyEl.hidden = cats.length > 0;
  } catch (e) {
    showToast(e.message, true);
  }
}

function openCategories(user) {
  categoryView.user = user;
  categoryUserEl.textContent = user;
  memoCard.hidden = true;
  memoEditCard.hidden = true;
  categoryCard.hidden = false;
  categoryCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  loadCategoryRows(user);
}

document.getElementById("memo-categories").addEventListener("click", () => {
  if (memoView.user) openCategories(memoView.user);
});

// カテゴリ管理を閉じてメモ一覧へ戻る。カテゴリ変更を反映するため取り直す。
document.getElementById("category-back").addEventListener("click", () => {
  categoryCard.hidden = true;
  if (categoryView.user) openMemos(categoryView.user);
  categoryView.user = null;
});

categoryCreateForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (!categoryView.user) return;
  const name = newCategoryEl.value.trim();
  if (!name) {
    showToast("カテゴリ名は必須です", true);
    return;
  }
  try {
    await api(`/api/users/${encodeURIComponent(categoryView.user)}/categories`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    showToast(`カテゴリ「${name}」を追加しました`);
    newCategoryEl.value = "";
    loadCategoryRows(categoryView.user);
  } catch (e) {
    showToast(e.message, true);
  }
});

document.getElementById("create-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const name = document.getElementById("new-name").value.trim();
  const display_name = document.getElementById("new-display").value.trim();
  const note = document.getElementById("new-note").value.trim();
  const is_admin = document.getElementById("new-admin").checked;
  if (!name) {
    showToast("ユーザー名は必須です", true);
    return;
  }
  try {
    await api("/api/users", {
      method: "POST",
      body: JSON.stringify({ name, display_name, note, is_admin }),
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
