"use strict";
/* The page of `canary ui`: plain JavaScript, no library, no network request but the local server. */
(function () {
  const STRINGS = JSON.parse(document.getElementById("strings").textContent);
  const STAGES = JSON.parse(document.getElementById("stage-names").textContent);
  const LANG = document.documentElement.lang === "tr" ? "tr" : "en";
  const TOKEN = new URLSearchParams(location.search).get("t") || "";
  const SCREENS = ["start", "mapping", "run", "result", "past"];
  const FORM_KEYS = ["folder", "out", "lang", "currency", "basis", "value", "curve", "discount_date",
    "value_date", "origin_axis", "origin_period", "development_period", "currency_view",
    "price_index", "lineage_format", "assumptions", "profiles"];

  const $ = (id) => document.getElementById(id);
  const S = (key, values) => {
    let text = STRINGS[key];
    if (text === undefined) { return key; }
    for (const name in values || {}) { text = text.split("{" + name + "}").join(String(values[name])); }
    return text;
  };
  const number = (value) => value === null || value === undefined ? "–"
    : new Intl.NumberFormat(LANG === "tr" ? "tr-TR" : "en-US", { maximumFractionDigits: 0 }).format(value);

  function h(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const name in attrs || {}) {
      const value = attrs[name];
      if (value === null || value === undefined || value === false) { continue; }
      if (name === "class") { node.className = value; }
      else if (name === "text") { node.textContent = value; }
      else if (name.startsWith("on")) { node.addEventListener(name.slice(2), value); }
      else { node.setAttribute(name, value === true ? "" : value); }
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) { continue; }
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }
  const clear = (node) => { node.replaceChildren(); return node; };
  const show = (node, on) => { node.hidden = !on; };
  const announce = (text) => { $("live").textContent = ""; setTimeout(() => { $("live").textContent = text; }, 50); };

  // --- calls to the local server ----------------------------------------------------------

  class ApiError extends Error {
    constructor(code, detail) { super(code); this.code = code; this.detail = detail || ""; }
  }
  async function api(path, body) {
    const options = { headers: { "X-Canary-Token": TOKEN } };
    if (body !== undefined) {
      options.method = "POST";
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let response;
    try { response = await fetch(path, options); }
    catch (error) { throw new ApiError("server_gone", ""); }
    let data = {};
    try { data = await response.json(); } catch (error) { /* not JSON */ }
    if (!response.ok || data.error) {
      const e = data.error || {};
      throw new ApiError(e.code || "http_" + response.status, e.detail);
    }
    return data;
  }
  const errorText = (error) => {
    const key = "error." + error.code;
    return STRINGS[key] !== undefined ? S(key, { detail: error.detail }) : error.code + (error.detail ? ": " + error.detail : "");
  };
  function showError(id, error) {
    const node = $(id);
    node.textContent = error ? errorText(error) : "";
    show(node, Boolean(error));
  }
  const urlFor = (path, params) => {
    const query = new URLSearchParams(Object.assign({ t: TOKEN }, params));
    return path + "?" + query.toString();
  };

  // --- state kept in memory (and the form in the tab, as a convenience) ---------------------

  const state = { scan: null, runKey: null, polling: null, lastRun: null, defaults: {}, busy: false };

  function readForm() {
    const form = {};
    for (const key of FORM_KEYS) { form[key] = $(key).value.trim(); }
    return form;
  }
  function writeForm(values) {
    for (const key of FORM_KEYS) { if (values[key] !== undefined && values[key] !== null) { $(key).value = values[key]; } }
  }
  function remember() {
    try { sessionStorage.setItem("canary-form", JSON.stringify(readForm())); } catch (error) { /* private window */ }
  }
  function restore() {
    try { return JSON.parse(sessionStorage.getItem("canary-form") || "{}"); } catch (error) { return {}; }
  }

  let commandTimer = null;
  function refreshCommand() {
    clearTimeout(commandTimer);
    commandTimer = setTimeout(async () => {
      try {
        const data = await api("/api/command", { form: readForm(), pending: state.scan ? state.scan.pending > 0 : false });
        $("command").textContent = data.command;
      } catch (error) { $("command").textContent = errorText(error); }
    }, 150);
  }

  // --- routing: the address after # decides the screen, so the back button works ---------------

  function route() {
    const [name, query] = location.hash.replace(/^#/, "").split("?");
    const screen = SCREENS.includes(name) ? name : "start";
    for (const id of SCREENS) { show($("screen-" + id), id === screen); }
    for (const link of document.querySelectorAll("nav a[href^='#']")) {
      if (link.getAttribute("href") === "#" + screen) { link.setAttribute("aria-current", "page"); } else { link.removeAttribute("aria-current"); }
    }
    stopPolling();
    const params = new URLSearchParams(query || "");
    if (screen === "run") { startPolling(); }
    if (screen === "result") { loadResult(params.get("out") || state.defaults.out, params.get("run") || ""); }
    if (screen === "past") { loadPast(); }
    if (screen === "mapping" && !state.scan) { location.hash = "#start"; return; }
    if (screen === "start") { refreshCommand(); }
    const heading = $(screen + "-title") || $("start-title");
    heading.focus({ preventScroll: false });
    announce(heading.textContent);
  }
  const go = (hash) => { if (location.hash === hash) { route(); } else { location.hash = hash; } };

  // --- Start ----------------------------------------------------------------------------------

  function setBusy(on) {
    state.busy = on;
    for (const id of ["check", "run-now", "demo", "mapping-save", "mapping-save-run", "mapping-run"]) { $(id).disabled = on; }
    document.body.style.cursor = on ? "progress" : "";
  }

  async function check(event) {
    if (event) { event.preventDefault(); }
    showError("start-error", null);
    setBusy(true);
    announce(S("start.checking"));
    try {
      state.scan = await api("/api/scan", { form: readForm() });
      state.scan.notice = "";
      renderMapping();
      go("#mapping");
    } catch (error) { showError("start-error", error); }
    finally { setBusy(false); }
  }

  async function startRun(path, body, errorBox) {
    setBusy(true);
    try {
      const data = await api(path, body);
      state.runKey = data.out;
      go("#run");
    } catch (error) { showError(errorBox, error); }
    finally { setBusy(false); }
  }
  const runNow = () => { showError("start-error", null); return startRun("/api/start", { form: readForm(), pending: state.scan ? state.scan.pending > 0 : true }, "start-error"); };
  const runDemo = () => { showError("start-error", null); return startRun("/api/demo", { lang: $("lang").value }, "start-error"); };

  // --- folder browser -------------------------------------------------------------------------

  const dialog = $("browser");
  let browsed = "";
  async function browseTo(path) {
    showError("browser-error", null);
    try {
      const data = await api(urlFor("/api/browse", { path: path || "" }));
      browsed = data.path;
      $("browser-path").value = data.path;
      const list = clear($("browser-list"));
      if (!data.path) {
        for (const root of data.roots) { list.append(entryItem(root, root, null)); }
        if (data.home) { list.append(entryItem(S("browser.home"), data.home, null)); }
        $("browser-counts").textContent = S("browser.pick_root");
        $("browser-use").disabled = true;
        return;
      }
      $("browser-use").disabled = false;
      const counts = data.counts;
      $("browser-counts").textContent = counts === null ? S("browser.unreadable")
        : S("browser.counts", { n: counts.spreadsheets, csv: counts.csv }) + (counts.csv ? " " + S("browser.csv_note") : "");
      if (data.parent !== null) { list.append(entryItem(S("browser.up"), data.parent, null)); }
      else { list.append(entryItem(S("browser.roots"), "", null)); }
      for (const folder of data.folders) { list.append(entryItem(folder.name, folder.path, folder.counts)); }
      if (data.more) { list.append(h("li", { class: "hint" }, S("browser.more", { n: data.more }))); }
    } catch (error) { showError("browser-error", error); }
  }
  function entryItem(label, path, counts) {
    const suffix = counts ? " (" + S("browser.n_sheets", { n: counts.spreadsheets }) + ")" : "";
    const button = h("button", { type: "button", class: "plain entry", onclick: () => browseTo(path) }, "📁 " + label + suffix);
    return h("li", {}, button);
  }
  function openBrowser() {
    const start = $("folder").value.trim();
    if (typeof dialog.showModal === "function") { dialog.showModal(); } else { dialog.setAttribute("open", ""); }
    browseTo(start);
    $("browser-path").focus();
  }
  function closeBrowser() { if (typeof dialog.close === "function") { dialog.close(); } else { dialog.removeAttribute("open"); } $("browse").focus(); }

  // --- Mapping --------------------------------------------------------------------------------

  const layerText = (layer) => STRINGS["layer." + layer] !== undefined ? S("layer." + layer) : layer;

  function renderMapping() {
    const scan = state.scan;
    const root = clear($("mapping-files"));
    const unrecognised = clear($("unrecognised"));
    let sheets = 0;
    const skipped = [];
    for (const file of scan.files) {
      if (!file.recognised) { skipped.push(file); }
      for (const sheet of file.sheets) {
        sheets += 1;
        root.append(sheetCard(sheet));
      }
    }
    for (const file of skipped) {
      unrecognised.append(h("li", {}, h("strong", {}, file.name), " – ", fileReason(file)));
    }
    show($("unrecognised-title"), skipped.length > 0);
    show($("unrecognised-hint"), skipped.length > 0);
    $("mapping-summary").textContent = S("mapping.summary", { folder: scan.folder, files: scan.files.length, sheets: sheets, pending: scan.pending });
    const notice = $("mapping-notice");
    notice.textContent = scan.notice || "";
    show(notice, Boolean(scan.notice));
    showError("mapping-error", null);
  }
  function fileReason(file) {
    if (file.error) { return S("mapping.unreadable", { reason: file.error }); }
    if (!file.sheets.length) { return S("mapping.no_headers"); }
    return file.sheets.map((s) => S("mapping.sheet_reason", { sheet: s.sheet, reason: s.reason })).join("; ");
  }

  function usedFields(sheet, except) {
    return new Set(sheet.mappings.filter((m, i) => i !== except && m.field).map((m) => m.field));
  }
  function sheetCard(sheet) {
    const id = "sheet-" + Math.random().toString(36).slice(2, 9);
    const card = h("article", { class: "sheet", "aria-labelledby": id });
    const conceptSelect = h("select", { id: id + "-concept", disabled: !sheet.editable, onchange: (e) => changeConcept(sheet, e.target.value, card) });
    conceptSelect.append(h("option", { value: "" }, S("mapping.skip_sheet")));
    for (const c of state.scan.concepts) { conceptSelect.append(h("option", { value: c.concept, selected: c.concept === sheet.concept }, c.concept + " (" + c.file_name + ")")); }
    if (sheet.concept === null) { conceptSelect.value = ""; }
    const badge = h("span", { class: "badge " + sheet.state }, S("state." + sheet.state));
    const head = h("div", { class: "sheet-head" },
      h("h3", { id: id }, sheet.file + " [" + sheet.sheet + "]"), badge);
    const meta = h("p", { class: "hint" },
      S("mapping.header_row", { row: sheet.header_row }) +
      (sheet.rows_above ? " " + S("mapping.rows_above", { n: sheet.rows_above }) : "") +
      (sheet.score !== null ? " · " + S("mapping.confidence", { score: Math.round(sheet.score * 100) }) : "") +
      (sheet.detail ? " (" + sheet.detail + ")" : ""));
    card.append(head, meta, h("div", { class: "field inline" }, h("label", { for: id + "-concept" }, S("mapping.concept")), conceptSelect));
    if (!sheet.editable) { card.append(h("p", { class: "hint" }, S("mapping.canonical"))); }
    if (sheet.concept === null) {
      card.append(h("p", { class: "warn" }, S("mapping.no_concept", { reason: sheet.reason })));
      if (sheet.candidates.length) { card.append(h("p", { class: "hint" }, S("mapping.candidates", { list: sheet.candidates.map((c) => c.concept + " " + c.detail).join("; ") }))); }
      return card;
    }
    const others = sheet.candidates.filter((c) => c.concept !== sheet.concept);
    if (others.length) { card.append(h("p", { class: "hint" }, S("mapping.candidates", { list: others.map((c) => c.concept + " " + c.detail).join("; ") }))); }
    if (sheet.amounts !== null) {
      const select = h("select", { id: id + "-amounts", disabled: !sheet.editable, onchange: (e) => { sheet.amounts = e.target.value; sheet.dirty = true; } },
        h("option", { value: "to_date", selected: sheet.amounts === "to_date" }, S("mapping.amounts_to_date")),
        h("option", { value: "incremental", selected: sheet.amounts === "incremental" }, S("mapping.amounts_incremental")));
      card.append(h("div", { class: "field inline" }, h("label", { for: id + "-amounts" }, S("mapping.amounts")), select));
      if (sheet.amounts_note) { card.append(h("p", { class: "hint" }, sheet.amounts_note)); }
    }
    const missing = h("p", { class: "warn", role: "status", hidden: true });
    card.append(missing);
    const table = h("table", {},
      h("caption", { class: "sr-only" }, sheet.file + " [" + sheet.sheet + "]"),
      h("thead", {}, h("tr", {}, ["#", "mapping.col_source", "mapping.col_field", "mapping.col_layer", "mapping.col_conf", "mapping.col_evidence"]
        .map((k, i) => h("th", { scope: "col" }, i === 0 ? "#" : S(k))))),
      h("tbody", {}, sheet.mappings.map((m, i) => mappingRow(sheet, m, i, id, missing, card))));
    card.append(h("div", { class: "scroll" }, table));
    updateMissing(sheet, missing);
    return card;
  }
  function mappingRow(sheet, m, index, id, missing, card) {
    let cell;
    if (m.personal) {
      cell = h("span", { class: "warn" }, S("mapping.personal", { kind: m.personal }));
    } else {
      const select = h("select", { id: id + "-col-" + index, "aria-label": S("mapping.target_for", { column: m.source }), disabled: !sheet.editable,
        onchange: (e) => changeField(sheet, index, e.target.value, card) });
      select.append(h("option", { value: "" }, S("mapping.unused")));
      for (const f of sheet.fields) {
        select.append(h("option", { value: f.name, selected: f.name === m.field }, f.name + (f.required ? " *" : "")));
      }
      select.value = m.field || "";
      cell = select;
    }
    return h("tr", {},
      h("td", {}, String(index + 1)),
      h("th", { scope: "row" }, m.source),
      h("td", {}, cell),
      h("td", {}, m.personal ? layerText("personal") : layerText(m.layer)),
      h("td", { class: "num" }, m.confidence === null || m.confidence === undefined ? "" : m.confidence.toFixed(2)),
      h("td", { class: "evidence" }, m.evidence));
  }
  function updateMissing(sheet, node) {
    const used = usedFields(sheet, -1);
    const missing = sheet.required.filter((f) => !used.has(f));
    node.textContent = missing.length ? S("mapping.missing", { fields: missing.join(", ") }) : "";
    show(node, missing.length > 0);
  }
  function changeField(sheet, index, value, card) {
    const target = value || null;
    if (target) {
      sheet.mappings.forEach((m, i) => { if (i !== index && m.field === target) { m.field = null; m.layer = "user"; m.evidence = target + " → " + sheet.mappings[index].source; } });
    }
    const m = sheet.mappings[index];
    m.field = target; m.layer = "user"; m.confidence = target ? 1 : null; m.evidence = target ? S("mapping.set_by_user") : S("mapping.not_used_user");
    sheet.dirty = true;
    card.replaceWith(sheetCard(sheet));
    announce(S("mapping.changed", { column: m.source, field: target || S("mapping.unused") }));
  }
  async function changeConcept(sheet, concept, card) {
    showError("mapping-error", null);
    try {
      const data = await api("/api/sheet", { form: readForm(), file: sheet.file, sheet: sheet.sheet, concept: concept || null });
      Object.assign(sheet, data, { dirty: true });
      card.replaceWith(sheetCard(sheet));
    } catch (error) { showError("mapping-error", error); }
  }

  function choices() {
    const out = [];
    for (const file of state.scan.files) {
      for (const sheet of file.sheets) {
        if (!sheet.editable) { continue; }
        const touched = sheet.dirty || sheet.state === "proposed";
        if (!touched) { continue; }
        const columns = {};
        for (const m of sheet.mappings) { if (!m.personal) { columns[m.source] = m.field; } }
        out.push({ file: sheet.file, sheet: sheet.sheet, concept: sheet.concept, amounts: sheet.amounts, columns: columns });
      }
    }
    return out;
  }
  async function saveMapping() {
    showError("mapping-error", null);
    setBusy(true);
    try {
      const data = await api("/api/mapping", { form: readForm(), sheets: choices() });
      data.notice = S("mapping.saved", { n: data.saved.length, folder: data.profiles });
      state.scan = data;
      renderMapping();
      announce(data.notice);
      return true;
    } catch (error) { showError("mapping-error", error); return false; }
    finally { setBusy(false); }
  }
  async function saveAndRun() { if (await saveMapping()) { await startRun("/api/start", { form: readForm(), pending: false }, "mapping-error"); } }
  const runUnsaved = () => startRun("/api/start", { form: readForm(), pending: state.scan.pending > 0 }, "mapping-error");

  // --- Run ------------------------------------------------------------------------------------

  function stageLabel(name) {
    const index = STAGES.indexOf(name);
    return index >= 0 ? S("stage." + index) : name;
  }
  function stopPolling() { if (state.polling) { clearInterval(state.polling); state.polling = null; } }
  function startPolling() { stopPolling(); state.lastRun = null; pollRun(); state.polling = setInterval(pollRun, 1000); }

  async function pollRun() {
    let run;
    try { run = await api("/api/run"); } catch (error) { showError("run-error", error); stopPolling(); return; }
    const finished = state.lastRun && state.lastRun.state === "running" && run.state === "done";
    state.lastRun = run;
    renderRun(run);
    if (run.state !== "running") { stopPolling(); }
    if (finished) { go("#result?" + new URLSearchParams({ out: run.out, run: run.run_id }).toString()); }
  }
  function renderRun(run) {
    if (run.state === "idle") { $("run-status").textContent = S("run.idle"); return; }
    $("run-status").textContent = S("run.state." + run.state, { kind: run.kind });
    $("run-elapsed").textContent = S("run.seconds", { s: Math.round(run.elapsed) });
    $("run-command").textContent = run.command;
    const list = clear($("stages"));
    for (const stage of run.stages) {
      const mark = { done: "✔", running: "…", failed: "✘", pending: "·" }[stage.state];
      list.append(h("li", { class: "stage " + stage.state, "aria-current": stage.state === "running" ? "step" : null },
        h("span", { class: "mark", "aria-hidden": "true" }, mark), " ", stageLabel(stage.name),
        stage.seconds !== null ? h("span", { class: "hint" }, " " + S("run.seconds", { s: stage.seconds })) : null,
        h("span", { class: "sr-only" }, " – " + S("run.stage." + stage.state))));
    }
    const running = run.state === "running";
    $("cancel").disabled = !running || run.cancel_requested;
    $("cancel-hint").textContent = run.cancel_requested ? S("run.cancelling") : S("run.cancel_hint");
    show($("cancel"), running);
    show($("cancel-hint"), running);
    const error = $("run-error");
    error.textContent = "";
    if (run.state === "failed") {
      error.append(h("strong", {}, S("run.failed")), " ", run.error || "");
      if (run.detail) { error.append(h("pre", {}, run.detail)); }
    }
    show(error, run.state === "failed");
    const partial = $("run-partial");
    partial.textContent = run.partial ? S("run.partial", { folder: run.partial }) : "";
    show(partial, Boolean(run.partial));
    renderFindings($("run-findings"), run.findings);
    show($("run-findings-box"), Boolean(run.findings));
    const after = $("run-after");
    show(after, !running);
    const toResult = $("run-to-result");
    if (run.state === "done") {
      toResult.hidden = false;
      toResult.setAttribute("href", "#result?" + new URLSearchParams({ out: run.out, run: run.run_id }).toString());
      if (state.lastNotified !== run.run_id + run.started) { state.lastNotified = run.run_id + run.started; announce(S("run.state.done", { kind: run.kind })); }
    } else { toResult.hidden = true; }
  }
  async function cancelRun() {
    try { await api("/api/cancel", {}); pollRun(); } catch (error) { showError("run-error", error); }
  }

  // --- findings (run screen and result screen) --------------------------------------------------

  function renderFindings(root, data) {
    clear(root);
    if (!data) { root.append(h("p", { class: "hint" }, S("findings.none_yet"))); return; }
    const c = data.counts;
    root.append(h("p", {}, S("findings.summary", { score: data.score === null ? "–" : data.score.toFixed(1), rules: data.rules === null ? "–" : data.rules,
      blocking: c.BLOCKING, warning: c.WARNING, info: c.INFO })));
    if (!data.findings.length) { root.append(h("p", {}, S("findings.clean"))); return; }
    const rows = data.findings.map((f) => h("tr", {},
      h("td", {}, h("span", { class: "sev " + f.severity }, S("severity." + f.severity))),
      h("td", { class: "rule" }, f.rule), h("td", { class: "num" }, f.count + "/" + f.checked), h("td", {}, f.message), h("td", { class: "evidence" }, f.examples.join("; "))));
    root.append(h("div", { class: "scroll" }, h("table", {},
      h("thead", {}, h("tr", {}, ["findings.col_severity", "findings.col_rule", "findings.col_count", "findings.col_what", "findings.col_examples"].map((k) => h("th", { scope: "col" }, S(k))))),
      h("tbody", {}, rows))));
    if (data.more) { root.append(h("p", { class: "hint" }, S("findings.more", { n: data.more }))); }
  }

  // --- Result ---------------------------------------------------------------------------------

  async function loadResult(out, run) {
    show($("result-body"), false);
    showError("result-error", null);
    try {
      const data = await api(urlFor("/api/result", { out: out, run: run }));
      renderResult(data, out);
      show($("result-body"), true);
    } catch (error) { showError("result-error", error); }
  }
  function renderResult(data, out) {
    const s = data.settings;
    const facts = clear($("result-facts"));
    const pairs = [
      ["result.run_id", h("code", {}, data.run_id)],
      ["result.date", data.date],
      ["result.version", data.version],
      ["result.folder", h("code", {}, data.folder)],
      ["result.language", s.language],
      ["result.currency", s.currency],
      ["result.basis", [s.reinsurance, s.value, s.currency_view].filter(Boolean).join(", ")],
      ["result.cut_off", s.cut_off],
    ];
    for (const [key, value] of pairs) { facts.append(h("dt", {}, S(key)), h("dd", {}, value === null || value === undefined ? "–" : value)); }
    const report = urlFor("/report", { out: out, run: data.run_id });
    const link = $("open-report");
    if (data.report) { link.setAttribute("href", report); link.removeAttribute("aria-disabled"); } else { link.setAttribute("href", "#"); link.setAttribute("aria-disabled", "true"); }
    const frame = $("report-frame");
    frame.hidden = true;
    frame.removeAttribute("src");
    $("show-report").setAttribute("aria-expanded", "false");
    $("show-report").textContent = S("result.show_report");
    $("show-report").onclick = () => {
      const open = frame.hidden;
      frame.hidden = !open;
      if (open) { frame.setAttribute("src", report); }
      $("show-report").setAttribute("aria-expanded", String(open));
      $("show-report").textContent = open ? S("result.hide_report") : S("result.show_report");
    };
    $("open-folder").onclick = async () => {
      try { const r = await api("/api/open", { out: out, run: data.run_id }); $("open-folder-hint").textContent = S("result.opened", { folder: r.opened }); }
      catch (error) { $("open-folder-hint").textContent = errorText(error); }
    };
    $("open-folder-hint").textContent = "";
    // headline numbers, as the terminal summary prints them
    const table = clear($("headline"));
    $("headline-note").textContent = data.headline.length ? S("result.headline_note", { currency: s.currency || "", basis: [s.reinsurance, s.value].filter(Boolean).join(", "), cut_off: s.cut_off || "–" }) : S("result.no_headline");
    if (data.headline.length) {
      const total = { paid: 0, incurred: 0, ultimate: 0, ibnr: 0 };
      table.append(h("thead", {}, h("tr", {}, ["result.col_line", "result.col_paid", "result.col_incurred", "result.col_ultimate", "result.col_ibnr"].map((k) => h("th", { scope: "col" }, S(k))))));
      const body = h("tbody", {});
      for (const row of data.headline) {
        for (const k in total) { total[k] += row[k]; }
        body.append(h("tr", {}, h("th", { scope: "row" }, row.segment + " / " + row.line),
          ["paid", "incurred", "ultimate", "ibnr"].map((k) => h("td", { class: "num" }, number(row[k])))));
      }
      table.append(body, h("tfoot", {}, h("tr", {}, h("th", { scope: "row" }, S("result.total")),
        ["paid", "incurred", "ultimate", "ibnr"].map((k) => h("td", { class: "num" }, number(total[k]))))));
    }
    renderFindings($("result-findings"), data.findings);
    const manifest = clear($("result-manifest"));
    manifest.append(h("p", {}, S("result.manifest_summary", { inputs: data.inputs.length, outputs: data.outputs })));
    manifest.append(h("ul", {}, data.inputs.map((i) => h("li", {}, h("strong", {}, i.name), " – ", i.concept || "–", " (", i.sheets.map((x) => x.name + ": " + number(x.rows) + " " + S("result.rows")).join(", "), ")"))));
    if (data.mappings.length) {
      manifest.append(h("p", {}, S("result.mappings")));
      manifest.append(h("ul", {}, data.mappings.map((m) => h("li", {}, m.file + " [" + m.sheet + "] → " + (m.concept || "–") + " (" + m.source + ")" +
        (m.personal_data_dropped.length ? " · " + S("result.personal_dropped", { columns: m.personal_data_dropped.join(", ") }) : "")))));
    }
    if (data.tables_not_used.length) {
      manifest.append(h("p", {}, S("result.not_used")));
      manifest.append(h("ul", {}, data.tables_not_used.map((t) => h("li", {}, t.file + " [" + t.sheet + "] – " + (t.concept || "–")))));
    }
  }

  // --- Past runs --------------------------------------------------------------------------------

  async function loadPast() {
    const field = $("past-out");
    if (!field.value) { field.value = $("out").value || state.defaults.out || ""; }
    showError("past-error", null);
    const table = clear($("past-table"));
    try {
      const data = await api(urlFor("/api/runs", { out: field.value }));
      field.value = data.out;
      show($("past-empty"), data.runs.length === 0);
      if (!data.runs.length) { return; }
      table.append(h("thead", {}, h("tr", {}, ["past.col_run", "past.col_date", "past.col_language", "past.col_basis", "past.col_actions"].map((k) => h("th", { scope: "col" }, S(k))))));
      const body = h("tbody", {});
      for (const run of data.runs) {
        const result = "#result?" + new URLSearchParams({ out: data.out, run: run.run_id }).toString();
        body.append(h("tr", {},
          h("th", { scope: "row" }, h("code", {}, run.run_id)),
          h("td", {}, run.date.replace("T", " ")),
          h("td", {}, run.language || "–"),
          h("td", {}, run.unreadable ? S("past.unreadable") : [run.reinsurance, run.value, run.currency].filter(Boolean).join(", ")),
          h("td", { class: "actions" },
            h("a", { class: "button", href: result }, S("past.result")),
            run.has_report ? h("a", { class: "button", href: urlFor("/report", { out: data.out, run: run.run_id }), target: "_blank", rel: "noopener" }, S("past.report")) : null,
            h("button", { type: "button", onclick: async (e) => { try { await api("/api/open", { out: data.out, run: run.run_id }); } catch (error) { showError("past-error", error); } } }, S("past.folder")))));
      }
      table.append(body);
    } catch (error) { showError("past-error", error); show($("past-empty"), false); }
  }

  // --- Quit -------------------------------------------------------------------------------------

  async function quit() {
    let force = false;
    try { const run = await api("/api/run"); if (run.state === "running") { if (!window.confirm(S("quit.confirm_running"))) { return; } force = true; } } catch (error) { /* gone */ }
    try { await api("/api/quit", { force: force }); } catch (error) { if (error.code !== "server_gone") { banner(error); return; } }
    document.body.replaceChildren(h("main", { class: "bye" }, h("h1", {}, S("quit.done")), h("p", {}, S("quit.done_text"))));
  }
  function banner(error) { const node = $("banner"); node.textContent = errorText(error); show(node, true); }

  // --- start -------------------------------------------------------------------------------------

  async function init() {
    try {
      const data = await api("/api/state");
      state.defaults = data;
      const saved = restore();
      writeForm(Object.assign({ out: data.out, profiles: data.profiles, lang: LANG }, saved));
      if (saved.lang === undefined) { $("lang").value = LANG; }
      if (data.run && data.run.state === "running" && !location.hash) { location.hash = "#run"; }
    } catch (error) { banner(error); }
    $("start-form").addEventListener("submit", check);
    $("start-form").addEventListener("input", () => { remember(); refreshCommand(); });
    $("start-form").addEventListener("change", () => { remember(); refreshCommand(); });
    $("run-now").addEventListener("click", runNow);
    $("demo").addEventListener("click", runDemo);
    $("browse").addEventListener("click", openBrowser);
    $("browser-close").addEventListener("click", closeBrowser);
    $("browser-go").addEventListener("click", () => browseTo($("browser-path").value.trim()));
    $("browser-path").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); browseTo($("browser-path").value.trim()); } });
    $("browser-use").addEventListener("click", () => { if (browsed) { $("folder").value = browsed; remember(); refreshCommand(); } closeBrowser(); });
    $("browser-form").addEventListener("submit", (e) => e.preventDefault());
    $("copy-command").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText($("command").textContent); announce(S("start.copied")); }
      catch (error) { const range = document.createRange(); range.selectNodeContents($("command")); const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range); announce(S("start.copy_manual")); }
    });
    $("mapping-save").addEventListener("click", saveMapping);
    $("mapping-save-run").addEventListener("click", saveAndRun);
    $("mapping-run").addEventListener("click", runUnsaved);
    $("cancel").addEventListener("click", cancelRun);
    $("past-refresh").addEventListener("click", loadPast);
    $("quit").addEventListener("click", quit);
    window.addEventListener("hashchange", route);
    route();
  }
  init();
})();
