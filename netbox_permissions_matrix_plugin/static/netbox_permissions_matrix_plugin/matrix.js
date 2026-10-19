/*
 * Permissions Matrix: draws the matrix from the plugin's REST API, stages changes in the browser, and sends them
 * through plan (review) and apply. Two modes share the code:
 *   - "matrix": object types x principals, every action at once as letter chips, or one action at a time;
 *   - "principal": object types x actions, for one group (the group tab).
 * No build step and no dependencies: plain DOM, fetch and <dialog>.
 */
(() => {
  "use strict";

  const root = document.querySelector(".pm-root");
  if (!root) return;

  const $ = (selector, scope = root) => scope.querySelector(selector);
  const $$ = (selector, scope = root) => Array.from(scope.querySelectorAll(selector));
  const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);
  const json = (value) => JSON.stringify(value);

  const mode = root.dataset.mode;
  const canEdit = root.dataset.canEdit === "true";
  const urls = {
    matrix: root.dataset.urlMatrix,
    principal: root.dataset.urlPrincipal,
    plan: root.dataset.urlPlan,
    apply: root.dataset.urlApply,
    import: root.dataset.urlImport,
    export: root.dataset.urlExport,
    whoCan: root.dataset.urlWhoCan,
    permission: root.dataset.urlPermission,
  };
  const params = new URLSearchParams(window.location.search);
  const listParam = (name) => params.getAll(name).filter(Boolean);

  const state = {
    action: params.get("action") || root.dataset.action || "*",
    includeUsers: params.has("users") ? params.get("users") === "1" : root.dataset.showUsers === "true",
    // Column keys picked in the column dialog ("group:3", "user:7"); null shows every column.
    shown: params.has("group_id") || params.has("user_id")
      ? new Set([...listParam("group_id").map((id) => `group:${id}`), ...listParam("user_id").map((id) => `user:${id}`)])
      : null,
    search: params.get("q") || "",
    app: params.get("app") || "",
    onlyGranted: params.get("granted") === "1",
    collapsed: new Set(),
    data: null,
    staged: new Map(), // "<principal key>|<object type>|<action>" -> cell change
    edits: new Map(), // "<principal key>|<action>" -> gear panel edit
    plan: null,
    importNotes: null, // warnings and errors from the last import, shown in the review
  };

  /* ---------- API ---------- */

  async function api(url, body) {
    const options = { credentials: "same-origin", headers: { Accept: "application/json" } };
    if (body !== undefined) {
      options.method = "POST";
      options.headers["Content-Type"] = "application/json";
      options.headers["X-CSRFToken"] = window.CSRF_TOKEN;
      options.body = json(body);
    }
    const response = await fetch(url, options);
    let data = null;
    try {
      data = await response.json();
    } catch (_) {
      data = { detail: `${response.status} ${response.statusText}` };
    }
    if (!response.ok) throw { status: response.status, data };
    return data;
  }

  function errorText(error) {
    const data = error && error.data;
    if (!data) return String(error);
    if (typeof data === "string") return data;
    if (data.detail) return data.detail;
    const lines = [];
    const walk = (value, path) => {
      if (Array.isArray(value)) value.forEach((v, i) => walk(v, typeof v === "object" ? `${path}[${i}]` : path));
      else if (value && typeof value === "object") Object.entries(value).forEach(([k, v]) => walk(v, path ? `${path}.${k}` : k));
      else lines.push(path ? `${path}: ${value}` : String(value));
    };
    walk(data, "");
    return lines.join("\n");
  }

  function message(text, kind = "info") {
    const box = $(".pm-message");
    box.innerHTML = text ? `<div class="alert alert-${kind} pm-alert">${esc(text).replace(/\n/g, "<br>")}</div>` : "";
  }

  /* ---------- URL state ---------- */

  // The page's filters as query parameters: the page URL and the export link share them.
  function filterParams() {
    const next = new URLSearchParams();
    if (mode === "matrix") {
      next.set("action", state.action);
      if (state.includeUsers) next.set("users", "1");
      if (state.shown) {
        for (const key of state.shown) {
          const [kind, id] = key.split(":");
          next.append(kind === "group" ? "group_id" : "user_id", id);
        }
      }
    }
    if (state.search) next.set("q", state.search);
    if (state.app) next.set("app", state.app);
    if (state.onlyGranted) next.set("granted", "1");
    return next;
  }

  function syncUrl() {
    const query = filterParams().toString();
    window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
  }

  /* ---------- Grid model (shared by both modes) ---------- */

  const LETTERS = { view: "V", add: "A", change: "C", delete: "D", render_config: "R", sync: "S" };
  const letter = (action) => LETTERS[action] || action.charAt(0).toUpperCase();
  // Every action in one grid: a cell holds one chip per action.
  const allMode = () => mode === "matrix" && state.data && state.data.action === "*";

  // A column knows its principal and, except in the all-actions grid, its action; a cell is (column, object type).
  function columns() {
    const data = state.data;
    if (mode === "matrix") {
      return data.columns.map((c) => ({
        key: c.key,
        label: c.name,
        kind: c.type,
        principal: { type: c.type, id: c.id },
        principalKey: c.key,
        principalName: c.name,
        action: data.action === "*" ? null : data.action,
        info: c,
      }));
    }
    const p = data.principal;
    return data.actions.map((a) => ({
      key: a.name,
      label: a.label,
      kind: "action",
      principal: { type: p.type, id: p.id },
      principalKey: p.key,
      principalName: p.name,
      action: a.name,
      info: data.columns[a.name],
      help: a.help_text,
    }));
  }

  // action defaults to the column's; the all-actions grid passes it per chip.
  function entry(col, ot, action = col.action) {
    const cells = state.data.cells;
    if (allMode()) return ((cells[col.key] || {})[ot] || {})[action] || null;
    if (mode === "matrix") return (cells[col.key] || {})[ot] || null;
    return (cells[ot] || {})[action] || null;
  }

  function enabled(row, col, action = col.action) {
    return mode === "matrix" && !allMode() ? row.enabled : row.enabled_actions.includes(action);
  }

  const cellKey = (col, ot, action = col.action) => `${col.principalKey}|${ot}|${action}`;

  function original(col, ot, action = col.action) {
    const e = entry(col, ot, action);
    return e ? e.state : "none";
  }

  function effective(col, ot, action = col.action) {
    const staged = state.staged.get(cellKey(col, ot, action));
    return staged ? staged.granted : original(col, ot, action) === "granted";
  }

  function setCell(col, ot, granted, action = col.action) {
    const key = cellKey(col, ot, action);
    const current = original(col, ot, action);
    // Back to where it started: nothing to stage. A constrained or disabled cell set to "not granted" is a revoke.
    if ((granted && current === "granted") || (!granted && current === "none")) state.staged.delete(key);
    else state.staged.set(key, { principal: col.principal, object_type: ot, action, granted });
  }

  // The actions a cell shows: one in the single-action views, every action in the all-actions grid.
  const cellActions = (col) => (allMode() ? state.data.actions.map((a) => a.name) : [col.action]);

  function visibleColumns() {
    const all = columns();
    if (mode !== "matrix" || !state.shown) return all;
    return all.filter((c) => state.shown.has(c.key));
  }

  function visibleRows(cols) {
    const needle = state.search.trim().toLowerCase();
    return state.data.rows.filter((row) => {
      if (state.app && row.app_label !== state.app) return false;
      if (needle && !`${row.label} ${row.object_type} ${row.app_name}`.toLowerCase().includes(needle)) return false;
      const any = (c) => cellActions(c).some((a) => effective(c, row.object_type, a) || original(c, row.object_type, a) !== "none");
      if (state.onlyGranted && !cols.some(any)) {
        return false;
      }
      return true;
    });
  }

  /* ---------- Rendering ---------- */

  function cellTitle(row, col, e, staged, action = col.action) {
    const lines = [`${row.label}: ${col.principalName}, ${action}`];
    if (e && e.perms.length) {
      for (const p of e.perms) {
        let line = p.name;
        if (!p.enabled) line += " (disabled)";
        if (p.constrained) line += ` where ${json(p.constraints)}`;
        if (p.principals.length > 1) line += ` (shared by ${p.principals.length})`;
        lines.push(line);
      }
    } else {
      lines.push("Not granted");
    }
    if (e && e.inherited) lines.push(`Also through: ${e.inherited.groups.join(", ")} (${e.inherited.state})`);
    if (staged) lines.push(staged.granted ? "Staged: grant" : "Staged: revoke");
    return lines.join("\n");
  }

  function chipHtml(row, col, action) {
    const ot = row.object_type;
    if (!enabled(row, col, action)) return `<span class="pm-chip pm-off" aria-hidden="true"></span>`;
    const e = entry(col, ot, action);
    const staged = state.staged.get(cellKey(col, ot, action));
    const shown = staged ? (staged.granted ? "granted" : "none") : original(col, ot, action);
    const classes = ["pm-chip", `pm-${shown}`];
    if (staged) classes.push("pm-is-staged");
    if (e && e.inherited) classes.push("pm-inherited");
    const title = esc(cellTitle(row, col, e, staged, action));
    const data = `data-col="${esc(col.key)}" data-ot="${esc(ot)}" data-action="${esc(action)}"`;
    if (!canEdit) return `<span class="${classes.join(" ")}" ${data} title="${title}" role="img" aria-label="${title}">${esc(letter(action))}</span>`;
    return `<button type="button" class="${classes.join(" ")}" ${data} title="${title}" aria-label="${title}" aria-pressed="${shown === "granted"}">${esc(letter(action))}</button>`;
  }

  function cellHtml(row, col) {
    const ot = row.object_type;
    if (allMode()) return `<td class="pm-td"><div class="pm-chips" data-col="${esc(col.key)}" data-ot="${esc(ot)}">${cellActions(col).map((a) => chipHtml(row, col, a)).join("")}</div></td>`;
    const e = entry(col, ot);
    const staged = state.staged.get(cellKey(col, ot));
    const shown = staged ? (staged.granted ? "granted" : "none") : original(col, ot);
    const classes = ["pm-cell", `pm-${shown}`];
    if (staged) classes.push("pm-is-staged");
    if (e && e.inherited) classes.push("pm-inherited");
    const title = esc(cellTitle(row, col, e, staged));
    const data = `data-col="${esc(col.key)}" data-ot="${esc(ot)}"`;
    if (!enabled(row, col)) return `<td class="pm-td pm-td-off"><span class="pm-cell pm-off" title="${esc(`${col.action} does not apply to ${row.label}`)}"></span></td>`;
    if (!canEdit) return `<td class="pm-td"><span class="${classes.join(" ")}" ${data} title="${title}" role="img" aria-label="${title}"></span></td>`;
    return `<td class="pm-td"><button type="button" class="${classes.join(" ")}" ${data} title="${title}" aria-label="${title}" aria-pressed="${shown === "granted"}"></button></td>`;
  }

  function headerHtml(col) {
    const icon = col.kind === "group" ? "mdi-account-group" : col.kind === "user" ? "mdi-account" : "mdi-key";
    const what = col.action ? `${col.principalName}, ${col.action}` : col.principalName;
    const gear = `<button type="button" class="btn btn-sm btn-ghost-secondary pm-gear" data-col="${esc(col.key)}" title="Permission settings for ${esc(what)}" aria-label="Permission settings for ${esc(what)}"><i class="mdi mdi-cog" aria-hidden="true"></i></button>`;
    if (allMode()) {
      // One toggle per action, lined up with the chips below.
      const toggles = canEdit
        ? `<div class="pm-chips pm-chips-head">${cellActions(col).map((a) => `<button type="button" class="pm-chip pm-head-chip pm-all-col" data-col="${esc(col.key)}" data-action="${esc(a)}" title="Toggle ${esc(a)} for the whole column">${esc(letter(a))}</button>`).join("")}</div>`
        : "";
      return `<th scope="col" class="pm-colhead pm-colhead-all"><div class="pm-colname" title="${esc(col.label)}"><i class="mdi ${icon}" aria-hidden="true"></i> ${esc(col.label)} ${gear}</div>${toggles}</th>`;
    }
    const all = canEdit
      ? `<button type="button" class="btn btn-sm btn-ghost-primary pm-all pm-all-col" data-col="${esc(col.key)}" title="Toggle the whole column">all</button>`
      : "";
    return `<th scope="col" class="pm-colhead"><div class="pm-colname" title="${esc(col.help || col.label)}"><i class="mdi ${icon}" aria-hidden="true"></i> ${esc(col.label)}</div><div class="pm-colctl">${gear}${all}</div></th>`;
  }

  function render() {
    const cols = visibleColumns();
    const rows = visibleRows(cols);
    const scroll = $(".pm-scroll");
    if (!cols.length) {
      scroll.innerHTML = `<div class="p-4 text-secondary">No columns to show. Use Columns or the Users switch.</div>`;
      updateBar();
      return;
    }
    const apps = new Map();
    for (const row of rows) {
      if (!apps.has(row.app_label)) apps.set(row.app_label, { name: row.app_name, rows: [] });
      apps.get(row.app_label).rows.push(row);
    }
    // "all" toggles every action on the line; in the all-actions grid, a letter per action follows it, toggling only that
    // action. Actions that do not apply to a row keep an empty slot so the letters line up.
    const allButton = (cls, attrs, title, row) => {
      if (!canEdit) return "";
      const all = `<button type="button" class="btn btn-sm btn-ghost-primary pm-all ${cls}" ${attrs} title="${title}">all</button>`;
      if (!allMode()) return all;
      const letters = state.data.actions
        .map((a) => (row && !row.enabled_actions.includes(a.name)
          ? '<span class="pm-chip pm-off" aria-hidden="true"></span>'
          : `<button type="button" class="pm-chip pm-head-chip ${cls}" ${attrs} data-action="${esc(a.name)}" title="${title}: ${esc(a.name)} only">${esc(letter(a.name))}</button>`))
        .join("");
      return `<span class="pm-rowctl">${all}<span class="pm-chips">${letters}</span></span>`;
    };
    let html = `<table class="pm-table"><thead><tr><th scope="col" class="pm-corner">${mode === "matrix" ? "Object type" : "Object type / action"}</th>${cols.map(headerHtml).join("")}</tr></thead><tbody>`;
    for (const [label, app] of apps) {
      const collapsed = state.collapsed.has(label);
      html += `<tr class="pm-app-row"><th scope="rowgroup" class="pm-rowhead"><button type="button" class="btn btn-sm btn-ghost-secondary pm-app-toggle" data-app="${esc(label)}" aria-expanded="${!collapsed}"><i class="mdi ${collapsed ? "mdi-chevron-right" : "mdi-chevron-down"}" aria-hidden="true"></i> ${esc(app.name)}</button>${allButton("pm-all-app", `data-app="${esc(label)}"`, "Toggle every row of this app")}</th><td class="pm-app-fill" colspan="${cols.length}"></td></tr>`;
      if (collapsed) continue;
      for (const row of app.rows) {
        const link = urls.whoCan.replace("__ot__", encodeURIComponent(row.object_type));
        html += `<tr><th scope="row" class="pm-rowhead"><a href="${esc(link)}" title="Who can: ${esc(row.object_type)}">${esc(row.label)}</a>${allButton("pm-all-row", `data-ot="${esc(row.object_type)}"`, "Toggle the whole row", row)}</th>${cols.map((c) => cellHtml(row, c)).join("")}</tr>`;
      }
    }
    if (!rows.length) html += `<tr><td class="p-4 text-secondary" colspan="${cols.length + 1}">No object type matches the filters.</td></tr>`;
    html += "</tbody></table>";
    scroll.innerHTML = html;
    updateBar();
  }

  function renderTabs() {
    const tabs = $(".pm-tabs");
    if (!tabs) return;
    const allActive = state.action === "*";
    const total = state.staged.size + state.edits.size;
    const allTab = `<li class="nav-item" role="presentation"><button type="button" role="tab" class="nav-link${allActive ? " active" : ""}" data-action="*" aria-selected="${allActive}" title="Every action at once">All actions${total && !allActive ? ` <span class="badge bg-primary text-primary-fg">${total}</span>` : ""}</button></li>`;
    tabs.innerHTML = allTab + state.data.actions
      .map((a) => {
        const active = a.name === state.action;
        const hint = a.freeform ? "Action found in existing permissions" : a.custom ? a.help_text || "Custom action" : "";
        return `<li class="nav-item" role="presentation"><button type="button" role="tab" class="nav-link${active ? " active" : ""}${a.custom || a.freeform ? " pm-tab-custom" : ""}" data-action="${esc(a.name)}" aria-selected="${active}" title="${esc(hint)}">${esc(a.label)}${stagedFor(a.name) ? ` <span class="badge bg-primary text-primary-fg">${stagedFor(a.name)}</span>` : ""}</button></li>`;
      })
      .join("");
  }

  function stagedFor(action) {
    let n = 0;
    for (const change of state.staged.values()) if (change.action === action) n += 1;
    return n;
  }

  function renderApps() {
    const select = $(".pm-app-filter");
    const seen = new Map();
    for (const row of state.data.rows) seen.set(row.app_label, row.app_name);
    select.innerHTML = `<option value="">All apps</option>${[...seen].map(([label, name]) => `<option value="${esc(label)}"${label === state.app ? " selected" : ""}>${esc(name)}</option>`).join("")}`;
  }

  function updateBar() {
    const bar = $(".pm-bar");
    if (!bar) return;
    const n = state.staged.size + state.edits.size;
    bar.hidden = n === 0;
    $(".pm-count", bar).textContent = `${n} change${n === 1 ? "" : "s"} staged`;
    if (mode === "matrix") renderTabs();
  }

  function refreshCell(col, ot) {
    const button = $$(".pm-cell, .pm-chips").find((el) => el.dataset.col === col.key && el.dataset.ot === ot);
    if (!button) return render();
    const row = state.data.rows.find((r) => r.object_type === ot);
    const td = button.closest("td");
    td.outerHTML = cellHtml(row, col);
    updateBar();
  }

  /* ---------- Loading ---------- */

  async function load() {
    message("");
    try {
      if (mode === "matrix") {
        const query = new URLSearchParams({ action: state.action, include_users: state.includeUsers ? "true" : "false" });
        for (const key of state.shown || []) if (key.startsWith("user:")) query.append("user_id", key.slice(5));
        state.data = await api(`${urls.matrix}?${query}`);
        renderTabs();
      } else {
        const [type, id] = root.dataset.principal.split(":");
        state.data = await api(`${urls.principal}?${new URLSearchParams({ type, id })}`);
      }
      renderApps();
      render();
    } catch (error) {
      $(".pm-scroll").innerHTML = "";
      message(errorText(error), "danger");
    }
  }

  /* ---------- Gear panel ---------- */

  // The column's permissions, each with its own form: every permission of the principal in the all-actions grid, the
  // ones granting the column's action otherwise. Edits are staged per permission ID.
  const panelPerms = (col) => col.info.perms || [col.info.simple, ...col.info.others].filter(Boolean);
  const editKey = (col, p) => `${col.principalKey}|#${p.id}`;

  function panelFor(col) {
    const dialog = $(".pm-panel");
    const perms = panelPerms(col);
    $("#pm-panel-title", dialog).textContent = col.action ? `${col.principalName}: ${col.action}` : `${col.principalName}: permissions`;
    const form = (p) => {
      const staged = state.edits.get(editKey(col, p)) || {};
      const value = (field, fallback) => (field in staged ? staged[field] : fallback);
      const constraints = value("constraints", p.constrained ? p.constraints : null);
      const id = (field) => `pm-p${p.id}-${field}`;
      const shared = p.principals.length > 1
        ? `<div class="alert alert-warning small p-2">Shared with ${esc(p.principals.map((x) => x.name).join(", "))}: edits here change their access too.</div>`
        : "";
      return `<details class="pm-perm card mb-2" data-perm="${p.id}"${Object.keys(staged).length ? " open" : ""}>
        <summary class="card-body p-2">${permSummary(p)}</summary>
        <div class="card-body p-2 pt-0">
          ${shared}
          <div class="mb-2"><label class="form-label" for="${id("name")}">Name</label>
            <input id="${id("name")}" class="form-control pm-p-name" maxlength="100" value="${esc(value("name", p.name))}"></div>
          <div class="mb-2"><label class="form-label" for="${id("description")}">Description</label>
            <input id="${id("description")}" class="form-control pm-p-description" maxlength="200" value="${esc(value("description", p.description))}"></div>
          <div class="form-check form-switch mb-2"><input id="${id("enabled")}" class="form-check-input pm-p-enabled" type="checkbox"${value("enabled", p.enabled) ? " checked" : ""}>
            <label class="form-check-label" for="${id("enabled")}">Enabled</label></div>
          <div class="mb-2"><label class="form-label" for="${id("constraints")}">Constraints</label>
            <textarea id="${id("constraints")}" class="form-control font-monospace pm-p-constraints" rows="3" placeholder='{"site__slug": "paris"}'>${esc(constraints ? JSON.stringify(constraints, null, 2) : "")}</textarea>
            <div class="form-text">Applies to every object type and action in this permission. An object, or a list of objects combined with OR; empty removes them. <code>$user</code> is the current user.</div></div>
        </div></details>`;
    };
    $(".pm-panel-body", dialog).innerHTML = `<div class="alert alert-danger pm-panel-error" hidden></div>${perms.length ? perms.map(form).join("") : '<p class="text-secondary small">No permissions yet: tick a cell first.</p>'}`;
    const stage = $(".pm-panel-stage", dialog);
    if (stage) stage.hidden = !perms.length;
    dialog.dataset.col = col.key;
    dialog.showModal();
  }

  function permSummary(p) {
    return `<strong>${esc(p.name)}</strong> <a href="${esc(permissionUrl(p.id))}" target="_blank" rel="noopener" title="Open in NetBox"><i class="mdi mdi-open-in-new" aria-hidden="true"></i></a>${p.enabled ? "" : ' <span class="badge bg-secondary-lt">disabled</span>'}${p.constrained ? ' <span class="badge bg-warning-lt">constrained</span>' : ""}
      <span class="small text-secondary">${esc(p.actions.join(", "))} on ${p.object_types.length} object type${p.object_types.length === 1 ? "" : "s"}</span>`;
  }

  function permissionUrl(id) {
    return urls.permission.replace(/\/0\/$/, `/${id}/`);
  }

  // One edit per changed form; a form put back to how it was drops its staged edit.
  function stagePanel() {
    const dialog = $(".pm-panel");
    const col = columns().find((c) => c.key === dialog.dataset.col);
    const errorBox = $(".pm-panel-error", dialog);
    const pending = [];
    for (const box of $$(".pm-perm", dialog)) {
      const p = panelPerms(col).find((x) => String(x.id) === box.dataset.perm);
      const edit = { principal: col.principal, perm_id: p.id };
      const name = $(".pm-p-name", box).value.trim();
      const description = $(".pm-p-description", box).value;
      const enabledValue = $(".pm-p-enabled", box).checked;
      const text = $(".pm-p-constraints", box).value.trim();
      if (name && name !== p.name) edit.name = name;
      if (description !== p.description) edit.description = description;
      if (enabledValue !== p.enabled) edit.enabled = enabledValue;
      let constraints = null;
      if (text) {
        try {
          constraints = JSON.parse(text);
        } catch (error) {
          errorBox.textContent = `${p.name}: constraints are not valid JSON: ${error.message}`;
          errorBox.hidden = false;
          box.open = true;
          return;
        }
      }
      if (json(constraints) !== json(p.constrained ? p.constraints : null)) edit.constraints = constraints;
      pending.push([editKey(col, p), edit]);
    }
    for (const [key, edit] of pending) {
      if (Object.keys(edit).length > 2) state.edits.set(key, edit);
      else state.edits.delete(key);
    }
    dialog.close();
    updateBar();
  }

  /* ---------- Column picker ---------- */

  function openColumns() {
    const dialog = $(".pm-columns-dialog");
    const all = columns();
    $(".pm-columns-body", dialog).innerHTML = all.length
      ? `<div class="pm-columns-list">${all.map((c) => `<label class="form-check"><input class="form-check-input" type="checkbox" value="${esc(c.key)}"${!state.shown || state.shown.has(c.key) ? " checked" : ""}><span class="form-check-label"><i class="mdi ${c.kind === "group" ? "mdi-account-group" : "mdi-account"}" aria-hidden="true"></i> ${esc(c.label)}</span></label>`).join("")}</div>`
      : `<p class="text-secondary">No groups or users.</p>`;
    dialog.showModal();
  }

  /* ---------- Review and apply ---------- */

  const changeSet = () => ({ changes: [...state.staged.values()], edits: [...state.edits.values()] });

  function principalsText(list) {
    return list.length ? list.map((p) => esc(p.name)).join(", ") : "nobody";
  }

  function fieldRows(before, after) {
    const fields = [
      ["Name", (p) => esc(p.name)],
      ["Description", (p) => esc(p.description) || '<span class="text-secondary">none</span>'],
      ["Enabled", (p) => (p.enabled ? "yes" : "no")],
      ["Actions", (p) => esc(p.actions.join(", "))],
      ["Object types", (p) => p.object_types.map((o) => `<code>${esc(o)}</code>`).join(" ")],
      ["Assigned to", (p) => principalsText(p.principals)],
      ["Constraints", (p) => (p.constrained ? `<code>${esc(json(p.constraints))}</code>` : '<span class="text-secondary">none</span>')],
    ];
    return fields
      .map(([label, show]) => {
        const a = before ? show(before) : null;
        const b = after ? show(after) : null;
        if (before && after && a === b) return "";
        if (before && after) return `<tr><th scope="row">${label}</th><td class="pm-before">${a}</td><td class="pm-after">${b}</td></tr>`;
        return `<tr><th scope="row">${label}</th><td colspan="2">${a ?? b}</td></tr>`;
      })
      .join("");
  }

  function renderPlan(plan) {
    const body = $(".pm-review-body");
    const labels = { create: ["Create", "bg-green-lt"], update: ["Change", "bg-blue-lt"], delete: ["Delete", "bg-red-lt"] };
    let html = importNotesHtml();
    if (plan.warnings.length) {
      html += `<div class="alert alert-warning"><ul class="m-0">${plan.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`;
    }
    if (!plan.operations.length) {
      html += `<p class="text-secondary">Nothing to change: the permissions already match what you staged.</p>`;
    } else {
      const counts = { create: 0, update: 0, delete: 0 };
      plan.operations.forEach((op) => (counts[op.op] += 1));
      html += `<p>${counts.create} to create, ${counts.update} to change, ${counts.delete} to delete. Nothing is written until you click Apply.</p>`;
    }
    for (const op of plan.operations) {
      const [label, badge] = labels[op.op];
      const perm = op.after || op.before;
      const name = op.id ? `<a href="${esc(permissionUrl(op.id))}" target="_blank" rel="noopener">${esc(perm.name)}</a>` : esc(perm.name);
      html += `<section class="pm-op card mb-2"><div class="card-body p-2">
        <div class="d-flex align-items-center gap-2 mb-1"><span class="badge ${badge}">${label}</span><strong>${name}</strong></div>
        <div class="small mb-1">Affects: ${principalsText(op.affects)}</div>
        ${op.reasons.length ? `<ul class="small text-secondary mb-1">${op.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
        <table class="table table-sm pm-diff mb-0">${op.op === "update" ? '<thead><tr><th></th><th scope="col">Before</th><th scope="col">After</th></tr></thead>' : ""}<tbody>${fieldRows(op.op === "create" ? null : op.before, op.op === "delete" ? null : op.after)}</tbody></table>
      </div></section>`;
    }
    body.innerHTML = html;
    $(".pm-apply").hidden = !plan.operations.length;
    $(".pm-apply").disabled = false;
  }

  function importNotesHtml() {
    const notes = state.importNotes;
    if (!notes) return "";
    const list = (items) => `<ul class="m-0">${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;
    let html = "";
    if (notes.errors.length) html += `<div class="alert alert-danger"><strong>Import: skipped entries</strong>${list(notes.errors)}</div>`;
    if (notes.warnings.length) html += `<div class="alert alert-warning"><strong>Import: left unchanged</strong>${list(notes.warnings)}</div>`;
    return html;
  }

  async function importFile(file) {
    let result;
    try {
      result = await api(urls.import, { yaml: await file.text() });
    } catch (error) {
      message(`Import failed: ${errorText(error)}`, "danger");
      return;
    }
    for (const c of result.changes) {
      const key = `${c.principal.type}:${c.principal.id}|${c.object_type}|${c.action}`;
      state.staged.set(key, { principal: c.principal, object_type: c.object_type, action: c.action, granted: c.granted });
    }
    state.importNotes = result.errors.length || result.warnings.length ? result : null;
    render();
    if (state.staged.size || state.edits.size) {
      message(`Imported ${file.name}: ${result.changes.length} cell change${result.changes.length === 1 ? "" : "s"} staged.`);
      review();
    } else {
      message(`Imported ${file.name}: the permissions already match the file.`, "success");
      $(".pm-message").insertAdjacentHTML("beforeend", importNotesHtml());
      state.importNotes = null;
    }
  }

  async function review() {
    const dialog = $(".pm-review-dialog");
    $(".pm-review-body", dialog).innerHTML = '<p class="text-secondary">Planning...</p>';
    $(".pm-apply", dialog).hidden = true;
    dialog.showModal();
    try {
      state.plan = await api(urls.plan, changeSet());
      renderPlan(state.plan);
    } catch (error) {
      $(".pm-review-body", dialog).innerHTML = `<div class="alert alert-danger">${esc(errorText(error)).replace(/\n/g, "<br>")}</div>`;
    }
  }

  async function apply() {
    const dialog = $(".pm-review-dialog");
    const button = $(".pm-apply", dialog);
    button.disabled = true;
    try {
      const result = await api(urls.apply, { ...changeSet(), token: state.plan.token });
      state.staged.clear();
      state.edits.clear();
      state.importNotes = null;
      dialog.close();
      message(`Applied: ${result.written.length} permission${result.written.length === 1 ? "" : "s"} written.`, "success");
      await load();
      message(`Applied: ${result.written.length} permission${result.written.length === 1 ? "" : "s"} written.`, "success");
    } catch (error) {
      const stale = error.status === 409;
      $(".pm-review-body", dialog).insertAdjacentHTML(
        "afterbegin",
        `<div class="alert alert-${stale ? "warning" : "danger"}">${esc(errorText(error))}${stale ? ' <button type="button" class="btn btn-sm btn-warning pm-reload">Reload the matrix</button>' : ""}</div>`,
      );
      button.disabled = stale;
    }
  }

  /* ---------- Events ---------- */

  function columnByKey(key) {
    return columns().find((c) => c.key === key);
  }

  // cells are [row, column] pairs; in the all-actions grid each pair expands to every action, unless one is given.
  function bulk(cells, action) {
    const targets = cells
      .flatMap(([row, col]) => (action ? [action] : cellActions(col)).map((a) => [row, col, a]))
      .filter(([row, col, a]) => enabled(row, col, a));
    if (!targets.length) return;
    const allOn = targets.every(([row, col, a]) => effective(col, row.object_type, a));
    for (const [row, col, a] of targets) setCell(col, row.object_type, !allOn, a);
    render();
  }

  root.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target || !root.contains(target)) return;
    if ((target.matches(".pm-cell") || (target.matches(".pm-chip") && !target.matches(".pm-head-chip"))) && canEdit) {
      const col = columnByKey(target.dataset.col);
      const ot = target.dataset.ot;
      const action = target.dataset.action || col.action;
      setCell(col, ot, !effective(col, ot, action), action);
      refreshCell(col, ot);
      return;
    }
    if (target.matches(".pm-tabs .nav-link")) {
      state.action = target.dataset.action;
      syncUrl();
      load();
      return;
    }
    if (target.matches(".pm-app-toggle")) {
      const app = target.dataset.app;
      if (state.collapsed.has(app)) state.collapsed.delete(app);
      else state.collapsed.add(app);
      render();
      return;
    }
    const cols = visibleColumns();
    const rows = visibleRows(cols);
    if (target.matches(".pm-all-col")) {
      const col = columnByKey(target.dataset.col);
      bulk(rows.filter((r) => !state.collapsed.has(r.app_label)).map((r) => [r, col]), target.dataset.action);
    } else if (target.matches(".pm-all-row")) {
      const row = rows.find((r) => r.object_type === target.dataset.ot);
      bulk(cols.map((c) => [row, c]), target.dataset.action);
    } else if (target.matches(".pm-all-app")) {
      bulk(rows.filter((r) => r.app_label === target.dataset.app).flatMap((r) => cols.map((c) => [r, c])), target.dataset.action);
    } else if (target.matches(".pm-gear")) {
      panelFor(columnByKey(target.dataset.col));
    } else if (target.matches(".pm-panel-stage")) {
      stagePanel();
    } else if (target.matches(".pm-discard")) {
      state.staged.clear();
      state.edits.clear();
      state.importNotes = null;
      render();
    } else if (target.matches(".pm-review")) {
      review();
    } else if (target.matches(".pm-apply")) {
      apply();
    } else if (target.matches(".pm-reload")) {
      state.staged.clear();
      state.edits.clear();
      state.importNotes = null;
      $(".pm-review-dialog").close();
      load();
    } else if (target.matches(".pm-columns-button")) {
      openColumns();
    } else if (target.matches(".pm-columns-all")) {
      $$(".pm-columns-body input").forEach((el) => (el.checked = true));
    } else if (target.matches(".pm-columns-apply")) {
      const picked = $$(".pm-columns-body input").filter((el) => el.checked).map((el) => el.value);
      state.shown = picked.length === columns().length ? null : new Set(picked);
      syncUrl();
      render();
    }
  });

  let searchTimer = null;
  $(".pm-search").value = state.search;
  $(".pm-search").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.search = event.target.value;
      syncUrl();
      render();
    }, 150);
  });
  $(".pm-app-filter").addEventListener("change", (event) => {
    state.app = event.target.value;
    syncUrl();
    render();
  });
  const onlyGranted = $(".pm-only-granted");
  onlyGranted.checked = state.onlyGranted;
  onlyGranted.addEventListener("change", () => {
    state.onlyGranted = onlyGranted.checked;
    syncUrl();
    render();
  });
  const users = $(".pm-users");
  if (users) {
    users.checked = state.includeUsers;
    users.addEventListener("change", () => {
      state.includeUsers = users.checked;
      syncUrl();
      load();
    });
  }

  const exportLink = $(".pm-export");
  if (exportLink && urls.export) {
    // The link follows the filters at click time; the "only rows with grants" switch does not narrow the export.
    exportLink.addEventListener("click", () => {
      const query = filterParams();
      query.delete("action");
      query.delete("granted");
      exportLink.href = `${urls.export}?${query}`;
    });
  }
  const importInput = $(".pm-import");
  if (importInput) {
    importInput.addEventListener("change", () => {
      const file = importInput.files[0];
      importInput.value = "";
      if (file) importFile(file);
    });
  }

  window.addEventListener("beforeunload", (event) => {
    if (state.staged.size || state.edits.size) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  load();
})();
