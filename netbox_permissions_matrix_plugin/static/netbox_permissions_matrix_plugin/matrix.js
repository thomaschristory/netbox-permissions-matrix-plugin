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
    const allButton = (cls, attrs, title) =>
      canEdit ? `<button type="button" class="btn btn-sm btn-ghost-primary pm-all ${cls}" ${attrs} title="${title}">all</button>` : "";
    let html = `<table class="pm-table"><thead><tr><th scope="col" class="pm-corner">${mode === "matrix" ? "Object type" : "Object type / action"}</th>${cols.map(headerHtml).join("")}</tr></thead><tbody>`;
    for (const [label, app] of apps) {
      const collapsed = state.collapsed.has(label);
      html += `<tr class="pm-app-row"><th scope="rowgroup" class="pm-rowhead"><button type="button" class="btn btn-sm btn-ghost-secondary pm-app-toggle" data-app="${esc(label)}" aria-expanded="${!collapsed}"><i class="mdi ${collapsed ? "mdi-chevron-right" : "mdi-chevron-down"}" aria-hidden="true"></i> ${esc(app.name)}</button>${allButton("pm-all-app", `data-app="${esc(label)}"`, "Toggle every row of this app")}</th><td class="pm-app-fill" colspan="${cols.length}"></td></tr>`;
      if (collapsed) continue;
      for (const row of app.rows) {
        const link = urls.whoCan.replace("__ot__", encodeURIComponent(row.object_type));
        html += `<tr><th scope="row" class="pm-rowhead"><a href="${esc(link)}" title="Who can: ${esc(row.object_type)}">${esc(row.label)}</a>${allButton("pm-all-row", `data-ot="${esc(row.object_type)}"`, "Toggle the whole row")}</th>${cols.map((c) => cellHtml(row, c)).join("")}</tr>`;
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
    for (const edit of state.edits.values()) if (edit.action === action) n += 1;
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

  function panelFor(col) {
    const dialog = $(".pm-panel");
    if (allMode()) return overviewPanel(col, dialog);
    const info = col.info || { simple: null, others: [] };
    const key = `${col.principalKey}|${col.action}`;
    const staged = state.edits.get(key) || {};
    const simple = info.simple;
    const pendingGrant = [...state.staged.values()].some(
      (c) => c.granted && c.action === col.action && `${c.principal.type}:${c.principal.id}` === col.principalKey,
    );
    $("#pm-panel-title", dialog).textContent = `${col.principalName}: ${col.action}`;
    let html = "";
    if (simple || pendingGrant) {
      const value = (field, fallback) => (field in staged ? staged[field] : fallback);
      const groupOptions = mode === "matrix"
        ? state.data.columns.filter((c) => c.type === "group" && c.key !== col.principalKey)
        : [];
      const userOptions = mode === "matrix"
        ? state.data.columns.filter((c) => c.type === "user" && c.key !== col.principalKey)
        : [];
      const options = (list, chosen) =>
        list.map((c) => `<option value="${c.id}"${(chosen || []).includes(c.id) ? " selected" : ""}>${esc(c.name)}</option>`).join("");
      html += `<h3 class="h4">Simple permission</h3>`;
      html += simple
        ? `<p class="text-secondary small">New grants of <strong>${esc(col.action)}</strong> for ${esc(col.principalName)} go into <a href="${esc(permissionUrl(simple.id))}">${esc(simple.name)}</a>.</p>`
        : `<p class="text-secondary small">This permission is created by your staged grants. You can name and describe it now.</p>`;
      html += `
        <div class="mb-2"><label class="form-label" for="pm-f-name">Name</label>
          <input id="pm-f-name" class="form-control" maxlength="100" value="${esc(value("name", simple ? simple.name : ""))}" placeholder="${simple ? "" : "Default name from the new_permission_name setting"}"></div>
        <div class="mb-2"><label class="form-label" for="pm-f-description">Description</label>
          <input id="pm-f-description" class="form-control" maxlength="200" value="${esc(value("description", simple ? simple.description : ""))}"></div>
        <div class="form-check form-switch mb-2"><input id="pm-f-enabled" class="form-check-input" type="checkbox"${value("enabled", simple ? simple.enabled : true) ? " checked" : ""}>
          <label class="form-check-label" for="pm-f-enabled">Enabled</label></div>
        <div class="mb-2"><label class="form-label" for="pm-f-constraints">Constraints</label>
          <textarea id="pm-f-constraints" class="form-control font-monospace" rows="3" placeholder='{"site__slug": "paris"}'>${esc("constraints" in staged && staged.constraints !== null ? json(staged.constraints) : "")}</textarea>
          <div class="form-text">An object, or a list of objects combined with OR. <code>$user</code> is the current user.</div></div>
        <div class="mb-2"><label class="form-label" for="pm-f-actions">Additional actions</label>
          <input id="pm-f-actions" class="form-control" value="${esc((staged.add_actions || []).join(", "))}" placeholder="change, delete"></div>`;
      if (groupOptions.length) {
        html += `<div class="mb-2"><label class="form-label" for="pm-f-groups">Also assign to groups</label><select id="pm-f-groups" class="form-select" multiple size="4">${options(groupOptions, staged.add_groups)}</select></div>`;
      }
      if (userOptions.length) {
        html += `<div class="mb-2"><label class="form-label" for="pm-f-users">Also assign to users</label><select id="pm-f-users" class="form-select" multiple size="4">${options(userOptions, staged.add_users)}</select></div>`;
      }
      html += `<div class="alert alert-warning pm-panel-warning" hidden>Constraints, additional actions, groups or users make this permission no longer simple: new grants of ${esc(col.action)} for ${esc(col.principalName)} will then go into a new permission.</div>`;
      html += `<div class="alert alert-danger pm-panel-error" hidden></div>`;
    } else {
      html += `<p class="text-secondary">${esc(col.principalName)} has no simple permission for <strong>${esc(col.action)}</strong> yet. Tick a cell in this column first; the permission it creates can then be edited here.</p>`;
    }
    html += `<h3 class="h4 mt-3">Other permissions granting ${esc(col.action)}</h3>`;
    html += info.others.length
      ? `<ul class="list-unstyled pm-others">${info.others.map(otherHtml).join("")}</ul>`
      : `<p class="text-secondary small">None.</p>`;
    $(".pm-panel-body", dialog).innerHTML = html;
    const stage = $(".pm-panel-stage", dialog);
    if (stage) stage.hidden = !(simple || pendingGrant);
    dialog.dataset.col = col.key;
    const warn = () => {
      const warning = $(".pm-panel-warning", dialog);
      if (!warning) return;
      const groups = $("#pm-f-groups", dialog);
      const users = $("#pm-f-users", dialog);
      warning.hidden = !(
        $("#pm-f-constraints", dialog).value.trim() ||
        $("#pm-f-actions", dialog).value.trim() ||
        (groups && groups.selectedOptions.length) ||
        (users && users.selectedOptions.length)
      );
    };
    $$("input, textarea, select", dialog).forEach((el) => el.addEventListener("input", warn));
    warn();
    dialog.showModal();
  }

  // The all-actions grid has no single simple permission per column: list everything the principal holds.
  function overviewPanel(col, dialog) {
    const perms = col.info.perms || [];
    $("#pm-panel-title", dialog).textContent = `${col.principalName}: permissions`;
    $(".pm-panel-body", dialog).innerHTML = `<p class="text-secondary small">Edit a permission from its own page, or switch to a single action tab to use the settings panel.</p>${perms.length ? `<ul class="list-unstyled pm-others">${perms.map(otherHtml).join("")}</ul>` : '<p class="text-secondary small">None.</p>'}`;
    const stage = $(".pm-panel-stage", dialog);
    if (stage) stage.hidden = true;
    dialog.dataset.col = col.key;
    dialog.showModal();
  }

  function otherHtml(p) {
    const others = p.principals.map((x) => x.name).join(", ");
    return `<li class="mb-2"><a href="${esc(permissionUrl(p.id))}">${esc(p.name)}</a>${p.enabled ? "" : ' <span class="badge bg-secondary-lt">disabled</span>'}${p.constrained ? ' <span class="badge bg-warning-lt">constrained</span>' : ""}
      <div class="small text-secondary">${esc(p.actions.join(", "))} on ${p.object_types.length} object type${p.object_types.length === 1 ? "" : "s"}; assigned to ${esc(others)}</div>
      ${p.constrained ? `<code class="small">${esc(json(p.constraints))}</code>` : ""}</li>`;
  }

  function permissionUrl(id) {
    return urls.permission.replace(/\/0\/$/, `/${id}/`);
  }

  function stagePanel() {
    const dialog = $(".pm-panel");
    const col = columns().find((c) => c.key === dialog.dataset.col);
    const simple = col.info && col.info.simple;
    const errorBox = $(".pm-panel-error", dialog);
    const edit = { principal: col.principal, action: col.action };
    const name = $("#pm-f-name", dialog).value.trim();
    const description = $("#pm-f-description", dialog).value;
    const enabledValue = $("#pm-f-enabled", dialog).checked;
    const constraintsText = $("#pm-f-constraints", dialog).value.trim();
    if (name && name !== (simple ? simple.name : "")) edit.name = name;
    if (description !== (simple ? simple.description : "")) edit.description = description;
    if (enabledValue !== (simple ? simple.enabled : true)) edit.enabled = enabledValue;
    if (constraintsText) {
      try {
        edit.constraints = JSON.parse(constraintsText);
      } catch (error) {
        errorBox.textContent = `Constraints are not valid JSON: ${error.message}`;
        errorBox.hidden = false;
        return;
      }
    }
    const actions = $("#pm-f-actions", dialog).value.split(/[\s,]+/).filter(Boolean);
    if (actions.some((a) => !/^[a-z_][a-z0-9_]{0,29}$/.test(a))) {
      errorBox.textContent = "Actions are lowercase names such as change or render_config.";
      errorBox.hidden = false;
      return;
    }
    if (actions.length) edit.add_actions = actions;
    const picked = (id) => {
      const select = $(id, dialog);
      return select ? Array.from(select.selectedOptions, (o) => Number(o.value)) : [];
    };
    if (picked("#pm-f-groups").length) edit.add_groups = picked("#pm-f-groups");
    if (picked("#pm-f-users").length) edit.add_users = picked("#pm-f-users");
    const key = `${col.principalKey}|${col.action}`;
    if (Object.keys(edit).length > 2) state.edits.set(key, edit);
    else state.edits.delete(key);
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
      bulk(cols.map((c) => [row, c]));
    } else if (target.matches(".pm-all-app")) {
      bulk(rows.filter((r) => r.app_label === target.dataset.app).flatMap((r) => cols.map((c) => [r, c])));
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
