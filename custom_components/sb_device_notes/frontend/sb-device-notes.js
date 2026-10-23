/* SB Device Notes — the sidebar page (/sb-device-notes).
 *
 * Devices tab: one row per device (and per waiting record) with its notes; search, filter
 * chips, a field picker; tap a row to edit its fields in place; tap a value's copy button
 * to copy it (a setup code, for the pairing screen). Fields tab: create, edit, delete fields.
 *
 * Talks to the integration over the websocket (sb_device_notes/list, …/set, …) and
 * re-reads whenever the integration says something changed (…/subscribe).
 * Rows use the shared SB row style (window.SBKit from the sb_ui_kit integration).
 */
const VERSION = "0.4.0";
const D = "sb_device_notes";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const kit = () => (window.SBKit && window.SBKit.api >= 1 ? window.SBKit : null);
let kitPromise = null;
const whenKit = () => kitPromise || (kitPromise = new Promise((resolve) => {
  if (kit()) { resolve(kit()); return; }
  const on = () => { if (kit()) { window.removeEventListener("sb-ui-kit-ready", on); resolve(kit()); } };
  window.addEventListener("sb-ui-kit-ready", on);
  setTimeout(() => { if (!kit()) import(`/sb_ui_kit_static/sb-ui-kit.js?v=retry-${Date.now()}`).then(on, () => {}); }, 3000);
  setTimeout(() => resolve(kit()), 15000);
}));

const TYPE_ICON = {
  text: "mdi:note-text-outline", long_text: "mdi:text-long", date: "mdi:calendar-check", number: "mdi:numeric",
  boolean: "mdi:checkbox-marked-outline", link: "mdi:link-variant", matter_code: "mdi:qrcode",
};
const TYPE_LABEL = {
  text: "Text", long_text: "Long text", date: "Date", number: "Number", boolean: "Yes / no", link: "Link", matter_code: "Matter setup code",
};
const SCOPE_LABEL = { all: "All devices", integrations: "Devices of chosen integrations", picked: "Only devices I add it to" };
const STRING_TYPES = ["text", "long_text", "link"];

// Copy that also works on plain http (navigator.clipboard needs a secure context).
async function copyText(text) {
  try { if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; } } catch (e) { /* fall back */ }
  const ta = document.createElement("textarea");
  ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false; try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  ta.remove(); return ok;
}

const STYLE = `
:host { display: block; min-height: 100vh; background: var(--primary-background-color); color: var(--primary-text-color); }
.bar { display: flex; align-items: center; gap: 4px; height: var(--header-height, 56px); padding: 0 12px; box-sizing: border-box; position: sticky; top: 0; z-index: 3;
       background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); border-bottom: 1px solid var(--divider-color); }
.title { font-size: 20px; flex: 1; margin-left: 4px; }
.tabs { display: flex; gap: 2px; }
.tabs button { font: inherit; font-size: 14px; color: inherit; background: none; border: none; padding: 6px 12px; border-radius: 16px; cursor: pointer; opacity: .8; }
.tabs button.on { opacity: 1; background: color-mix(in srgb, currentColor 14%, transparent); font-weight: 500; }
.page { padding: 16px; } .col { max-width: 900px; margin: 0 auto; }
ha-card { display: block; }
.tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 0 16px 12px; }
.search { flex: 1 1 220px; display: flex; align-items: center; gap: 6px; border: 1px solid var(--divider-color); border-radius: 18px; padding: 0 10px; height: 36px;
          background: var(--card-background-color); --mdc-icon-size: 18px; color: var(--secondary-text-color); }
.search input { flex: 1; border: none; outline: none; background: none; font: inherit; font-size: 14px; color: var(--primary-text-color); min-width: 0; }
select.pick { font: inherit; font-size: 14px; height: 36px; padding: 0 8px; border-radius: 18px; border: 1px solid var(--divider-color);
              background: var(--card-background-color); color: var(--primary-text-color); color-scheme: light dark; max-width: 100%; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 16px 12px; }
.chip { font: inherit; font-size: 13px; height: 30px; padding: 0 12px; border-radius: 15px; border: 1px solid var(--divider-color);
        background: none; color: var(--primary-text-color); cursor: pointer; }
.chip.on { background: color-mix(in srgb, var(--primary-color) 16%, transparent); border-color: transparent; color: var(--primary-color); font-weight: 500; }
.chip .n { opacity: .7; margin-left: 4px; }
.sbk-open { cursor: pointer; }
.vals { display: flex; flex-direction: column; gap: 2px; margin-top: 2px; }
.val { display: flex; flex-wrap: wrap; align-items: center; gap: 0 6px; font-size: 13px; min-height: 28px; }
.val .vc { display: inline-flex; align-items: center; gap: 4px; min-width: 0; max-width: 100%; }
.val .k { color: var(--secondary-text-color); white-space: nowrap; }
.val .v { color: var(--primary-text-color); overflow-wrap: anywhere; }
.val .v.code { font-family: var(--code-font-family, monospace); font-size: 14px; font-weight: 600; letter-spacing: .03em; white-space: nowrap; overflow-wrap: normal; }
@media (max-width: 600px) { .page { padding: 8px; } .editor { padding-left: 16px; } .ed-row { grid-template-columns: 1fr; } .ed-err { grid-column: 1; } }
.val .v.empty { color: var(--secondary-text-color); font-style: italic; }
.val a.v { color: var(--primary-color); }
.copy { border: none; background: none; cursor: pointer; color: var(--secondary-text-color); padding: 2px; border-radius: 12px; width: 28px; height: 28px;
        display: inline-flex; align-items: center; justify-content: center; --mdc-icon-size: 16px; flex: 0 0 28px; }
.copy:hover { background: color-mix(in srgb, var(--primary-text-color) 10%, transparent); color: var(--primary-color); }
.copy.done { color: var(--success-color, #43a047); }
.editor { padding: 4px 16px 16px 64px; border-top: 1px dashed var(--divider-color); }
.ed-row { display: grid; grid-template-columns: minmax(110px, 180px) 1fr; gap: 6px 12px; align-items: center; margin: 8px 0; }
.ed-row > span { color: var(--secondary-text-color); font-size: 13px; }
.ed-row input, .ed-row textarea, .ed-row select, .fe select, .fe input {
  font: inherit; font-size: 14px; padding: 7px 9px; border-radius: 6px; border: 1px solid var(--divider-color);
  background: var(--card-background-color); color: var(--primary-text-color); color-scheme: light dark; min-width: 0; width: 100%; box-sizing: border-box; }
.ed-row textarea { min-height: 70px; resize: vertical; }
.ed-err { grid-column: 2; color: var(--error-color); font-size: 12.5px; }
.ed-btns { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 12px; }
.ed-btns .sp { flex: 1; }
.sbk-btn.primary { background: var(--primary-color); border-color: transparent; color: var(--text-primary-color, #fff); }
.msg { padding: 8px 16px; font-size: 13px; color: var(--secondary-text-color); }
.msg.err { color: var(--error-color); }
.fe { padding: 8px 16px 16px; border-top: 1px dashed var(--divider-color); display: grid; grid-template-columns: minmax(110px, 160px) 1fr; gap: 8px 12px; align-items: center; }
.fe > span { color: var(--secondary-text-color); font-size: 13px; }
.fe .ints { grid-column: 2; display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 13px; }
.fe .ints label { display: inline-flex; align-items: center; gap: 4px; }
.fe .ints input { width: auto; }
.fe .full { grid-column: 1 / -1; }
.foot { color: var(--secondary-text-color); font-size: 12px; margin: 12px 4px 0; }
.foot a { color: var(--primary-color); }
`;

class SbDeviceNotesPanel extends HTMLElement {
  constructor() {
    super();
    this._tab = "devices"; this._q = ""; this._show = "notes"; this._field = "";
    this._open = null; this._menu = null; this._confirm = null; this._err = {}; this._msg = "";
    this._fieldOpen = null; this._copied = null;
  }

  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (this._menuBtn) this._menuBtn.hass = h;
    if (first) this._init();
  }
  set narrow(v) { this._narrow = v; if (this._menuBtn) this._menuBtn.narrow = v; }
  set route(_v) {}
  set panel(_v) {}

  connectedCallback() { if (this._hass && !this._unsub && this._ready) this._subscribe(); }
  disconnectedCallback() { if (this._unsub) { this._unsub.then((u) => u && u()).catch(() => {}); this._unsub = null; } if (this._unaway) this._unaway(); }

  async _init() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${STYLE}</style>
      <div class="bar"><ha-menu-button></ha-menu-button><div class="title">Device Notes</div>
        <div class="tabs"><button data-tab="devices" class="on">Devices</button><button data-tab="fields">Fields</button></div></div>
      <div class="page"><div class="col"><ha-card><div class="body"><div class="sbk-wait">Loading…</div></div></ha-card>
        <div class="foot">SB Device Notes ${VERSION} · <a href="/config/integrations/integration/${D}">Integration page</a></div></div></div>`;
    this._menuBtn = root.querySelector("ha-menu-button");
    this._menuBtn.hass = this._hass; this._menuBtn.narrow = this._narrow;
    root.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
      this._tab = b.dataset.tab; this._open = null; this._menu = null; this._confirm = null; this._fieldOpen = null;
      root.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
      this._render();
    }));
    const K = await whenKit();
    if (K?.sheet) root.adoptedStyleSheets = [K.sheet, ...root.adoptedStyleSheets];
    this._ready = true;
    await this._load();
    this._subscribe();
  }

  _subscribe() {
    this._unsub = this._hass.connection.subscribeMessage(() => this._scheduleLoad(), { type: `${D}/subscribe` });
    this._unsub.catch((e) => { this._msg = String(e?.message || e); this._render(); });
  }

  _scheduleLoad() { clearTimeout(this._lt); this._lt = setTimeout(() => this._load(), 250); }

  async _load() {
    try { this._data = await this._hass.callWS({ type: `${D}/list` }); this._loadErr = null; }
    catch (e) { this._loadErr = String(e?.message || e); }
    // Don't redraw under an open editor (it would wipe what's being typed).
    if (this._open && this.shadowRoot.querySelector(".editor")) return;
    if (this._fieldOpen && this.shadowRoot.querySelector(".fe")) return;
    this._render();
  }

  // ---- helpers ------------------------------------------------------------------------
  _fields() { return this._data?.fields || []; }
  _fieldById(id) { return this._fields().find((f) => f.id === id); }
  _items() {
    // devices + waiting records, as one list of rows
    const d = this._data; if (!d) return [];
    const rows = d.devices.map((x) => ({ ...x, key: `d:${x.device_id}`, waiting: false }));
    for (const w of d.waiting) rows.push({ ...w, key: `w:${w.record_id}`, waiting: true, visible: Object.keys(w.values), device_id: null });
    return rows;
  }
  _shownFields(row) {
    const f = this._field;
    if (f) return row.visible.includes(f) || row.values[f] ? [f] : [];
    return row.visible.filter((id) => this._fieldById(id));
  }
  _matches(row) {
    const hasVal = Object.keys(row.values).length > 0;
    const f = this._field;
    const missingOf = (id) => row.visible.includes(id) && !row.values[id];
    if (this._show === "notes" && !(f ? !!row.values[f] : hasVal)) return false;
    if (this._show === "waiting" && !row.waiting) return false;
    if (this._show === "missing" && (row.waiting || !(f ? missingOf(f) : row.visible.some(missingOf)))) return false;
    if (this._show === "all" && row.waiting) return false;
    const q = this._q.trim().toLowerCase();
    if (!q) return true;
    const hay = [row.name, row.area, row.manufacturer, row.model, ...Object.values(row.values).map((v) => v.display)].join(" ").toLowerCase();
    return q.split(/\s+/).every((t) => hay.includes(t) || hay.replace(/-/g, "").includes(t.replace(/-/g, "")));
  }
  _count(show) { const s = this._show; this._show = show; const q = this._q; this._q = ""; const n = this._items().filter((r) => this._matches(r)).length; this._show = s; this._q = q; return n; }

  // ---- render -----------------------------------------------------------------------------
  _render() {
    const body = this.shadowRoot?.querySelector(".body"); if (!body) return;
    const K = kit();
    if (this._loadErr) { body.innerHTML = `<div class="msg err">${esc(this._loadErr)}</div>`; return; }
    if (!this._data || !K) { body.innerHTML = `<div class="sbk-wait">Loading…</div>`; return; }
    body.innerHTML = this._tab === "fields" ? this._fieldsHtml(K) : this._devicesHtml(K);
    this._wire(body);
  }

  _devicesHtml(K) {
    const rows = this._items().filter((r) => this._matches(r))
      // waiting first, then by area (no area last), then by name
      .sort((a, b) => (Number(b.waiting) - Number(a.waiting)) || (Number(!a.area) - Number(!b.area))
        || (a.area || "").localeCompare(b.area || "") || (a.name || "").localeCompare(b.name || ""));
    const chips = [["notes", "With notes"], ["missing", this._field ? `Missing ${this._fieldById(this._field)?.name || ""}` : "Missing a value"], ["waiting", "Waiting"], ["all", "All devices"]]
      .map(([k, l]) => `<button class="chip ${this._show === k ? "on" : ""}" data-show="${k}">${esc(l)}<span class="n">${this._count(k)}</span></button>`).join("");
    const fieldOpts = [`<option value="">All fields</option>`, ...this._fields().map((f) => `<option value="${esc(f.id)}" ${this._field === f.id ? "selected" : ""}>${esc(f.name)}</option>`)].join("");
    return `<div class="sbk-head"><h2>Devices</h2><span class="sbk-count">${rows.length} shown</span></div>
      <div class="tools"><label class="search"><ha-icon icon="mdi:magnify"></ha-icon><input class="q" placeholder="Search name, area, model, code…" value="${esc(this._q)}"></label>
        <select class="pick fsel" aria-label="Field">${fieldOpts}</select></div>
      <div class="chips">${chips}</div>
      ${this._msg ? `<div class="msg err">${esc(this._msg)}</div>` : ""}
      ${rows.length ? rows.map((r) => this._rowHtml(r, K)).join("") : `<div class="sbk-empty">Nothing matches.</div>`}`;
  }

  _valueHtml(row, fid) {
    const f = this._fieldById(fid); if (!f) return "";
    const v = row.values[fid];
    let val;
    if (!v) val = `<span class="v empty">not set</span>`;
    else if (f.type === "link") val = `<a class="v" href="${esc(v.raw)}" target="_blank" rel="noopener">${esc(v.display)}</a>`;
    else val = `<span class="v ${f.type === "matter_code" ? "code" : ""}">${esc(f.type === "long_text" && v.display.length > 140 ? v.display.slice(0, 140) + "…" : v.display)}</span>`;
    const copyKey = `${row.key}|${fid}`;
    const copy = v && f.type !== "boolean"
      ? `<button class="copy ${this._copied === copyKey ? "done" : ""}" data-copy="${esc(copyKey)}" title="Copy" aria-label="Copy ${esc(f.name)}"><ha-icon icon="${this._copied === copyKey ? "mdi:check" : "mdi:content-copy"}"></ha-icon></button>` : "";
    return `<div class="val"><span class="k">${esc(f.name)}</span><span class="vc">${val}${copy}</span></div>`;
  }

  _rowHtml(row, K) {
    const shown = this._shownFields(row);
    const icon = row.waiting ? ["warn", "mdi:clock-alert-outline"] : row.unavailable ? ["bad", "mdi:lan-disconnect"]
      : Object.keys(row.values).length ? ["armed", "mdi:note-text-outline"] : ["idle", "mdi:note-outline"];
    const sub = [row.waiting ? "Waiting for re-pair" : null, row.area, [row.manufacturer, row.model].filter(Boolean).join(" ")].filter(Boolean);
    const menuOpen = this._menu === row.key;
    const items = row.waiting
      ? [{ act: "forget", icon: "mdi:delete-outline", label: "Forget these notes…", danger: true }]
      : [{ act: "edit", icon: "mdi:pencil-outline", label: "Edit" }, { act: "device", icon: "mdi:devices", label: "Open device page" }, "-",
         { act: "forget", icon: "mdi:delete-outline", label: "Forget all notes…", danger: true, disabled: !row.record_id }];
    if (this._confirm === row.key) {
      return `<div class="sbk-confirm" data-key="${esc(row.key)}"><p>Forget every value stored for <b>${esc(row.name)}</b>?</p>
        <button class="sbk-btn" data-act="no">Cancel</button><button class="sbk-btn danger" data-act="yes">Forget</button></div>`;
    }
    return `<div class="sbk-row ${row.unavailable ? "off" : ""}" data-key="${esc(row.key)}">
        <div class="sbk-open" role="button" tabindex="0" data-act="toggle">
          <div class="sbk-ico sm ${icon[0]}"><ha-icon icon="${icon[1]}"></ha-icon></div>
          <div class="sbk-txt"><div class="sbk-t">${esc(row.name || "?")}</div>
            <div class="sbk-s">${sub.map(esc).join('<span class="sbk-dot"></span>')}</div>
            ${shown.length ? `<div class="vals">${shown.map((fid) => this._valueHtml(row, fid)).join("")}</div>` : ""}</div>
        </div>
        <button class="sbk-kb ${menuOpen ? "on" : ""}" data-act="menu" aria-label="More for ${esc(row.name)}">${K.kbIcon}</button>
        ${menuOpen ? K.menu(`${row.name} actions`, items) : ""}
      </div>${this._open === row.key && !row.waiting ? this._editorHtml(row) : ""}`;
  }

  _inputHtml(f, v) {
    const raw = v ? v.raw : "";
    const id = `in-${f.id}`;
    if (f.type === "long_text") return `<textarea id="${id}" data-f="${esc(f.id)}">${esc(raw)}</textarea>`;
    if (f.type === "date") return `<input id="${id}" type="date" data-f="${esc(f.id)}" value="${esc(raw)}">`;
    if (f.type === "number") return `<input id="${id}" type="number" step="any" data-f="${esc(f.id)}" value="${esc(raw)}">`;
    if (f.type === "boolean") return `<select id="${id}" data-f="${esc(f.id)}"><option value="">—</option>
      <option value="true" ${raw === true ? "selected" : ""}>Yes</option><option value="false" ${raw === false ? "selected" : ""}>No</option></select>`;
    const val = f.type === "matter_code" && v ? v.display : raw;
    const ph = f.type === "matter_code" ? "1234-567-8901 or MT:…" : f.type === "link" ? "https://…" : "";
    return `<input id="${id}" type="${f.type === "link" ? "url" : "text"}" data-f="${esc(f.id)}" value="${esc(val)}" placeholder="${ph}" ${f.type === "matter_code" ? 'inputmode="numeric" autocomplete="off"' : ""}>`;
  }

  _editorHtml(row) {
    const ids = row.visible.filter((id) => this._fieldById(id));
    const addable = this._fields().filter((f) => !row.visible.includes(f.id));
    return `<div class="editor" data-key="${esc(row.key)}">
      ${ids.map((id) => { const f = this._fieldById(id); return `<div class="ed-row"><span><label for="in-${esc(id)}">${esc(f.name)}</label></span>${this._inputHtml(f, row.values[id])}
        ${this._err[id] ? `<div class="ed-err">${esc(this._err[id])}</div>` : ""}</div>`; }).join("")}
      ${ids.length ? "" : `<div class="msg">No fields on this device yet: add one below.</div>`}
      <div class="ed-btns">${addable.length ? `<select class="pick addf"><option value="">+ Add a field…</option>${addable.map((f) => `<option value="${esc(f.id)}">${esc(f.name)}</option>`).join("")}</select>` : ""}
        <span class="sp"></span><button class="sbk-btn" data-act="cancel">Cancel</button><button class="sbk-btn primary" data-act="save">Save</button></div>
      ${this._err._ ? `<div class="msg err">${esc(this._err._)}</div>` : ""}</div>`;
  }

  _fieldsHtml(K) {
    const fields = this._fields();
    const rows = fields.map((f) => {
      const key = `f:${f.id}`;
      if (this._confirm === key) {
        return `<div class="sbk-confirm" data-key="${esc(key)}"><p>Delete <b>${esc(f.name)}</b>${f.usage ? ` and its ${f.usage} value${f.usage === 1 ? "" : "s"}` : ""}? Its entities go too.</p>
          <button class="sbk-btn" data-act="no">Cancel</button><button class="sbk-btn danger" data-act="yes">Delete</button></div>`;
      }
      const scope = f.scope === "integrations" ? `Devices of ${f.integrations.join(", ")}` : SCOPE_LABEL[f.scope];
      const menuOpen = this._menu === key;
      return `<div class="sbk-row dense" data-key="${esc(key)}">
          <div class="sbk-open" role="button" tabindex="0" data-act="ftoggle"><div class="sbk-ico sm armed"><ha-icon icon="${TYPE_ICON[f.type]}"></ha-icon></div>
            <div class="sbk-txt"><div class="sbk-t">${esc(f.name)}</div><div class="sbk-s">${esc(TYPE_LABEL[f.type])}<span class="sbk-dot"></span>${esc(scope)}<span class="sbk-dot"></span>${f.usage} device${f.usage === 1 ? "" : "s"}</div></div></div>
          <button class="sbk-kb ${menuOpen ? "on" : ""}" data-act="menu" aria-label="More for ${esc(f.name)}">${K.kbIcon}</button>
          ${menuOpen ? K.menu(`${f.name} actions`, [{ act: "fedit", icon: "mdi:pencil-outline", label: "Edit" }, "-", { act: "fdelete", icon: "mdi:delete-outline", label: "Delete…", danger: true }]) : ""}
        </div>${this._fieldOpen === f.id ? this._fieldEditorHtml(f) : ""}`;
    }).join("");
    return `<div class="sbk-head"><h2>Fields</h2><span class="sbk-count">${fields.length}</span>
        <button class="sbk-add" data-act="fadd"><ha-icon icon="mdi:plus"></ha-icon>Add field</button></div>
      ${this._fieldOpen === "__new" ? this._fieldEditorHtml(null) : ""}
      ${this._msg ? `<div class="msg err">${esc(this._msg)}</div>` : ""}
      ${rows || `<div class="sbk-empty">No fields.</div>`}
      <div class="sbk-note">Scope decides which devices show a field. A device with a value always shows it. Renaming keeps every value and entity ID; text, long text and link convert into each other.</div>`;
  }

  _fieldEditorHtml(f) {
    const d = this._data;
    const isNew = !f;
    const types = isNew ? d.types : STRING_TYPES.includes(f.type) ? STRING_TYPES : [f.type];
    const cur = f || { name: "", type: "text", scope: "picked", integrations: [] };
    const ints = d.integrations.map((i) => `<label><input type="checkbox" value="${esc(i)}" ${cur.integrations.includes(i) ? "checked" : ""}>${esc(i)}</label>`).join("");
    return `<div class="fe" data-field="${esc(isNew ? "__new" : f.id)}">
      <span>Name</span><input class="fn" value="${esc(cur.name)}" placeholder="e.g. Filter size">
      <span>Type</span><select class="ft">${types.map((t) => `<option value="${t}" ${t === cur.type ? "selected" : ""}>${esc(TYPE_LABEL[t])}</option>`).join("")}</select>
      <span>Scope</span><select class="fs">${d.scopes.map((s) => `<option value="${s}" ${s === cur.scope ? "selected" : ""}>${esc(SCOPE_LABEL[s])}</option>`).join("")}</select>
      <div class="ints" style="${cur.scope === "integrations" ? "" : "display:none"}">${ints}</div>
      ${this._err.field ? `<div class="msg err full">${esc(this._err.field)}</div>` : ""}
      <div class="ed-btns full"><span class="sp"></span><button class="sbk-btn" data-act="fcancel">Cancel</button><button class="sbk-btn primary" data-act="fsave">${isNew ? "Create" : "Save"}</button></div></div>`;
  }

  // ---- events -----------------------------------------------------------------------------
  _setMenu(key) {
    this._menu = key;
    if (this._unaway) { this._unaway(); this._unaway = null; }
    if (key) this._unaway = kit().away(() => { this._menu = null; this._unaway?.(); this._unaway = null; this._render(); });
    this._render();
  }

  _row(key) { return this._items().find((r) => r.key === key); }

  _wire(body) {
    const q = body.querySelector("input.q");
    if (q) {
      q.addEventListener("input", () => { this._q = q.value; const pos = q.selectionStart; this._render(); const n = this.shadowRoot.querySelector("input.q"); n.focus(); n.setSelectionRange(pos, pos); });
    }
    body.querySelector("select.fsel")?.addEventListener("change", (e) => { this._field = e.target.value; this._render(); });
    body.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { this._show = c.dataset.show; this._render(); }));
    body.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async (e) => {
      e.stopPropagation();
      const [key, fid] = b.dataset.copy.split("|");
      const row = this._row(key); const v = row?.values[fid]; if (!v) return;
      if (await copyText(v.display)) { this._copied = b.dataset.copy; this._render(); setTimeout(() => { this._copied = null; this._render(); }, 1500); }
    }));
    body.querySelectorAll(".sbk-open").forEach((o) => {
      const go = () => {
        const key = o.closest("[data-key]").dataset.key;
        if (o.dataset.act === "ftoggle") { this._fieldOpen = this._fieldOpen === key.slice(2) ? null : key.slice(2); this._err = {}; this._render(); return; }
        if (key.startsWith("w:")) return;
        this._open = this._open === key ? null : key; this._err = {}; this._render();
        if (this._open) this.shadowRoot.querySelector(".editor input, .editor textarea, .editor select")?.focus();
      };
      o.addEventListener("click", (e) => { if (!e.target.closest("a, .copy")) go(); });
      o.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });
    body.querySelectorAll("button[data-act=menu]").forEach((b) => b.addEventListener("click", () => {
      const key = b.closest("[data-key]").dataset.key; this._setMenu(this._menu === key ? null : key);
    }));
    body.querySelectorAll(".sbk-menu button").forEach((b) => b.addEventListener("click", () => this._menuAct(b.closest("[data-key]").dataset.key, b.dataset.act)));
    body.querySelectorAll(".sbk-confirm").forEach((c) => {
      const key = c.dataset.key;
      c.querySelector("[data-act=no]").addEventListener("click", () => { this._confirm = null; this._render(); });
      c.querySelector("[data-act=yes]").addEventListener("click", () => this._confirmed(key));
    });
    const ed = body.querySelector(".editor");
    if (ed) {
      ed.querySelector("[data-act=cancel]").addEventListener("click", () => { this._open = null; this._err = {}; this._render(); });
      ed.querySelector("[data-act=save]").addEventListener("click", () => this._save(ed));
      ed.querySelector("select.addf")?.addEventListener("change", (e) => this._addField(ed.dataset.key, e.target.value));
      ed.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); this._save(ed); } if (e.key === "Escape") { this._open = null; this._render(); } });
    }
    body.querySelector("[data-act=fadd]")?.addEventListener("click", () => { this._fieldOpen = this._fieldOpen === "__new" ? null : "__new"; this._err = {}; this._render(); });
    const fe = body.querySelector(".fe");
    if (fe) {
      const fs = fe.querySelector(".fs");
      fs.addEventListener("change", () => { fe.querySelector(".ints").style.display = fs.value === "integrations" ? "" : "none"; });
      fe.querySelector("[data-act=fcancel]").addEventListener("click", () => { this._fieldOpen = null; this._err = {}; this._render(); });
      fe.querySelector("[data-act=fsave]").addEventListener("click", () => this._saveField(fe));
    }
  }

  async _menuAct(key, act) {
    this._setMenu(null);
    if (act === "edit") { this._open = key; this._err = {}; this._render(); return; }
    if (act === "device") { this._nav(`/config/devices/device/${key.slice(2)}`); return; }
    if (act === "forget" || act === "fdelete") { this._confirm = key; this._render(); return; }
    if (act === "fedit") { this._fieldOpen = key.slice(2); this._err = {}; this._render(); }
  }

  async _confirmed(key) {
    this._confirm = null; this._msg = "";
    try {
      if (key.startsWith("f:")) await this._hass.callWS({ type: `${D}/field_delete`, field: key.slice(2) });
      else {
        const row = this._row(key);
        if (row?.record_id) await this._hass.callWS({ type: `${D}/forget`, record_id: row.record_id });
      }
    } catch (e) { this._msg = String(e?.message || e); }
    await this._load();
  }

  async _addField(key, fid) {
    if (!fid) return;
    try { await this._hass.callWS({ type: `${D}/add_to_device`, device_id: key.slice(2), field: fid }); this._err = {}; }
    catch (e) { this._err = { _: String(e?.message || e) }; }
    const editor = this.shadowRoot.querySelector(".editor");
    const typed = editor ? this._collect(editor) : {};
    this._data = await this._hass.callWS({ type: `${D}/list` });
    this._render();
    // keep what was typed before the field was added
    for (const [f, v] of Object.entries(typed)) { const el = this.shadowRoot.querySelector(`.editor [data-f="${CSS.escape(f)}"]`); if (el) el.value = v; }
    this.shadowRoot.querySelector(`.editor [data-f="${CSS.escape(fid)}"]`)?.focus();
  }

  _collect(ed) { const out = {}; ed.querySelectorAll("[data-f]").forEach((el) => { out[el.dataset.f] = el.value; }); return out; }

  async _save(ed) {
    const row = this._row(ed.dataset.key); if (!row) return;
    const typed = this._collect(ed);
    this._err = {};
    for (const [fid, val] of Object.entries(typed)) {
      const f = this._fieldById(fid); const v = row.values[fid];
      const before = !v ? "" : f.type === "matter_code" ? v.display : f.type === "boolean" ? String(v.raw) : String(v.raw);
      if (val === before) continue;
      let value = val.trim() === "" ? null : f.type === "boolean" ? val === "true" : val;
      try { await this._hass.callWS({ type: `${D}/set`, device_id: row.device_id, field: fid, value }); }
      catch (e) { this._err[fid] = String(e?.message || e); }
    }
    if (Object.keys(this._err).length) {
      this._data = await this._hass.callWS({ type: `${D}/list` });
      this._render();
      for (const [f, v] of Object.entries(typed)) { const el = this.shadowRoot.querySelector(`.editor [data-f="${CSS.escape(f)}"]`); if (el && this._err[f]) el.value = v; }
      return;
    }
    this._open = null;
    await this._load();
  }

  async _saveField(fe) {
    const id = fe.dataset.field;
    const name = fe.querySelector(".fn").value.trim();
    const ftype = fe.querySelector(".ft").value;
    const scope = fe.querySelector(".fs").value;
    const integrations = [...fe.querySelectorAll(".ints input:checked")].map((i) => i.value);
    try {
      if (id === "__new") await this._hass.callWS({ type: `${D}/field_add`, name, field_type: ftype, scope, integrations });
      else await this._hass.callWS({ type: `${D}/field_update`, field: id, name, field_type: ftype, scope, integrations });
      this._fieldOpen = null; this._err = {};
    } catch (e) { this._err = { field: String(e?.message || e) }; this._render(); return; }
    await this._load();
  }

  _nav(path) { history.pushState(null, "", path); window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } })); }
}

// Define it, and again if HA's scoped-registry swap loses it (see sb-background, 2026-10-18).
const ensureDefined = () => {
  if (customElements.get("sb-device-notes-panel")) return;
  try { customElements.define("sb-device-notes-panel", class extends SbDeviceNotesPanel {}); } catch (e) { /* defined meanwhile */ }
};
ensureDefined();
setInterval(ensureDefined, 2000);
console.info(`%c SB-DEVICE-NOTES %c v${VERSION} `, "background:#37474f;color:#fff", "background:#90a4ae;color:#000");
