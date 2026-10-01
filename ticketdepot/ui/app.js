// Ticketdepot UI. Talks to the local server: POST /api/<method> with the per-launch
// token, GET for downloads. Rules, labels and thresholds come from the server
// (ticketdepot/rules.py) — nothing policy-related is hardcoded here.

const TOKEN = document.querySelector('meta[name="csrf"]').content;

async function call(method, ...args) {
  const res = await fetch(`/api/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Ticketdepot-Token": TOKEN },
    body: JSON.stringify(args),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  el.append(...children.flat().filter((c) => c != null && c !== false));
  return el;
}

const FILTER_THRESHOLD = 10; // filters stay behind the toggle up to this many tickets
const TABS = ["todo", "vorrat", "claimed", "future", "all"];
const TODO_STATES = new Set(["ask", "needs_arrival", "choose", "claim", "waiting"]);
const WEEKDAYS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];

const state = { journeys: [], summary: null, config: null, filtersOpen: false, open: new Set(), arrivalOpen: new Set() };
const params = new URLSearchParams(location.search);
const view = {
  tab: TABS.includes(params.get("tab")) ? params.get("tab") : "todo",
  q: params.get("q") || "",
  chip: params.get("chip") || "",
  band: params.get("band") || "",
  frist: params.get("frist") === "1",
  von: params.get("von") || "",
  nach: params.get("nach") || "",
};

// --- formatting ----------------------------------------------------------------

const eur = (n) => (n ?? 0).toLocaleString("de-DE", { style: "currency", currency: "EUR" });
const dt = (iso) => new Date(iso);
const hm = (iso) => dt(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
const de = (iso) => (iso ? iso.slice(0, 10).split("-").reverse().join(".") : "");
function dayLabel(iso) {
  const d = dt(iso);
  const dm = `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.`;
  return `${WEEKDAYS[d.getDay()]} ${dm}${d.getFullYear() !== new Date().getFullYear() ? d.getFullYear() : ""}`;
}
const fold = (s) => (s || "").toLowerCase().replace(/ß/g, "ss").replace(/[^0-9a-zäöü]/g, "");
const todayIso = () => new Date().toLocaleDateString("sv-SE");

function delayText(v) {
  if (v.disruption) return v.disruption;
  if (v.early_departure && (v.delay_min ?? 0) < 20) return "Abfahrt zu früh";
  if (v.delay_min == null) return null;
  return v.delay_min > 0 ? `+${v.delay_min} min` : "pünktlich";
}

function ruleLink(key) {
  const rule = state.config.rules[key];
  if (!rule || !rule.source_url) return null;
  return h("a", { class: "rule-link", href: rule.source_url, target: "_blank", rel: "noopener noreferrer", title: rule.text },
    state.config.rule_link_label);
}

const forceMajeure = () => h("p", { class: "fm" }, state.config.force_majeure_line, " ", ruleLink("hoehere_gewalt"));

// --- loading ---------------------------------------------------------------------

async function load() {
  const data = await call("overview");
  state.journeys = data.journeys;
  state.summary = data.summary;
  state.config = data.config;
  render();
}

function replaceJourney(j) {
  const i = state.journeys.findIndex((x) => x.id === j.id);
  if (i >= 0) state.journeys[i] = j;
}

// --- filtering ---------------------------------------------------------------------

function groups() {
  const js = state.journeys;
  return {
    todo: js.filter((j) => TODO_STATES.has(j.verdict.state)),
    vorrat: js.filter((j) => j.verdict.state === "reuse").sort((a, b) => a.verdict.reuse_until.localeCompare(b.verdict.reuse_until)),
    claimed: js.filter((j) => j.verdict.state === "claimed"),
    future: js.filter((j) => j.verdict.state === "future").reverse(),
    all: js,
  };
}

const filtersActive = () => Boolean(view.q || (view.tab === "all" && view.chip) || view.band || view.frist || (view.tab === "vorrat" && (view.von || view.nach)));

function matches(j) {
  const v = j.verdict;
  if (view.q) {
    const q = fold(view.q);
    const hay = [j.order_number, j.notes, j.origin, j.destination, ...j.legs.flatMap((l) => [l.train, l.origin, l.destination])].map(fold).join("|");
    if (!hay.includes(q)) return false;
  }
  if (view.tab === "all" && view.chip && !v.outcomes.includes(view.chip)) return false;
  if (view.band && v.band !== view.band) return false;
  if (view.frist && !v.due_soon) return false;
  if (view.tab === "vorrat") {
    if (view.von && !fold(j.origin).startsWith(fold(view.von))) return false;
    if (view.nach && !fold(j.destination).startsWith(fold(view.nach))) return false;
  }
  return true;
}

function syncUrl() {
  const p = new URLSearchParams();
  if (view.tab !== "todo") p.set("tab", view.tab);
  for (const k of ["q", "chip", "band", "von", "nach"]) if (view[k]) p.set(k, view[k]);
  if (view.frist) p.set("frist", "1");
  const qs = p.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

// --- rendering ---------------------------------------------------------------------

function render() {
  syncUrl();
  renderTiles();
  const g = groups();
  for (const tab of TABS) $(`#count-${tab}`).textContent = g[tab].length;
  for (const b of $$(".tabs [data-tab]")) b.setAttribute("aria-selected", b.dataset.tab === view.tab);

  const many = state.journeys.length > FILTER_THRESHOLD;
  const toggle = $("#filter-toggle");
  toggle.hidden = !many;
  // up to FILTER_THRESHOLD tickets the filters only show up when something (URL, tile) set one
  const listFilter = Boolean(view.q || view.band || view.frist || (view.tab === "all" && view.chip));
  $("#filters").hidden = !((many && state.filtersOpen) || listFilter);
  toggle.setAttribute("aria-expanded", !$("#filters").hidden);
  renderChips(g[view.tab]);

  const route = $("#route");
  route.hidden = view.tab !== "vorrat" || g.vorrat.length === 0;
  route.von.value = view.von;
  route.nach.value = view.nach;
  const stations = [...new Set(g.vorrat.flatMap((j) => [j.origin, j.destination]))].sort();
  $("#stations").replaceChildren(...stations.map((s) => h("option", { value: s })));

  const shown = g[view.tab].filter(matches);
  $("#list").replaceChildren(...shown.map(card));
  const active = filtersActive();
  $("#result-bar").hidden = !active;
  $("#result-count").textContent = `${shown.length} ${shown.length === 1 ? "Treffer" : "Treffer"}`;

  const empty = $("#empty");
  empty.hidden = shown.length > 0;
  if (!state.journeys.length) {
    empty.replaceChildren(
      h("p", { class: "empty-title" }, "Noch keine Tickets"),
      h("p", {}, "Importiere ein DB-Ticket-PDF über „PDF importieren“, per Drag & Drop oder „Aus Downloads“."),
    );
  } else {
    const msg = active ? "Keine Treffer für diese Filter." : { todo: "Nichts offen – alles erledigt.", vorrat: "Kein Ticket im Vorrat.", claimed: "Keine offenen Anträge.", future: "Keine anstehenden Reisen.", all: "" }[view.tab];
    empty.replaceChildren(h("p", {}, msg));
  }
}

function renderTiles() {
  const s = state.summary;
  const tile = (label, value, note, cls, onclick) =>
    h("button", { class: `tile ${cls}`, type: "button", onclick }, h("span", { class: "label" }, label), h("span", { class: "value" }, value), h("span", { class: "note" }, note));
  $("#tiles").replaceChildren(
    tile("Erstattung offen", eur(s.open_eur), s.open_count ? `${s.open_count} Antrag${s.open_count === 1 ? "" : "e"} bereit` : "nichts zu beantragen", s.open_count ? "money" : "", () => setTab("todo")),
    tile("Offene Fragen", s.needs_input, "Gefahren? Ankunft? Geld oder später?", s.needs_input ? "attention" : "", () => setTab("todo")),
    h("div", { class: "tile-wrap" },
      tile("Bald fällig", s.due_soon, "Anträge und Vorrat", s.due_soon ? "attention" : "", () => {
        Object.assign(view, { tab: "all", frist: true });
        state.filtersOpen = true;
        render();
      }),
      h("a", { class: "tile-link", href: "/ics/alle.ics", download: "" }, "Alle Fristen in Kalender")),
  );
}

function renderChips(inTab) {
  const cfg = state.config;
  const chip = (label, pressed, count, onclick, title) =>
    h("button", { type: "button", class: "chip-btn", "aria-pressed": pressed, title, onclick, disabled: !pressed && count === 0 }, label, h("span", { class: "count" }, count));
  const outcomes = view.tab === "all"
    ? Object.entries(cfg.outcomes).map(([key, label]) =>
        chip(label, view.chip === key, inTab.filter((j) => j.verdict.outcomes.includes(key)).length, () => {
          view.chip = view.chip === key ? "" : key;
          render();
        }))
    : [];
  $("#chips-outcome").replaceChildren(...outcomes);
  $("#chips-outcome").hidden = !outcomes.length;
  $("#chips-band").replaceChildren(
    ...cfg.bands.map((b) =>
      chip(b.label, view.band === b.key, inTab.filter((j) => j.verdict.band === b.key).length, () => {
        view.band = view.band === b.key ? "" : b.key;
        render();
      }, b.explain)),
    chip("Bald fällig", view.frist, inTab.filter((j) => j.verdict.due_soon).length, () => {
      view.frist = !view.frist;
      render();
    }),
  );
  $("#search").value = view.q;
}

// --- the card ----------------------------------------------------------------------

function card(j) {
  const v = j.verdict;
  const delay = delayText(v);
  const late = Boolean(v.disruption) || v.early_departure || (v.delay_min ?? 0) >= 20;
  const open = state.open.has(j.id);
  const el = h("article", { class: `card state-${v.state}`, dataset: { id: j.id } },
    h("header", { class: "card-head" },
      h("span", { class: "date" }, dayLabel(j.departure)),
      h("span", { class: "sep", "aria-hidden": "true" }, "·"),
      h("span", { class: "route" }, `${j.origin} → ${j.destination}`),
      delay && v.state !== "future" ? h("span", { class: `delay ${late ? "late" : ""}` }, delay) : null,
    ),
    h("div", { class: "card-body" }, body(j)),
    h("footer", { class: "card-foot" },
      dueLine(v),
      h("button", { type: "button", class: "link details-toggle", "aria-expanded": open, onclick: () => toggleDetails(j.id) }, open ? "Details ‹" : "Details ›"),
    ),
    open ? details(j) : null,
  );
  return el;
}

function dueLine(v) {
  if (!v.due) return h("span", { class: "due" });
  if (v.overdue) return h("span", { class: "due soon" }, `Eigene Frist ${de(v.claim_deadline)} verpasst · laut bahn.de noch bis ${de(v.due)}`);
  const text = v.due_kind === "vorrat" ? `Gültig bis ${de(v.due)}` : `Frist: ${de(v.due)}`;
  return h("span", { class: `due ${v.due_soon ? "soon" : ""}` }, text, v.due_soon ? " · bald fällig" : "");
}

function body(j) {
  const v = j.verdict;
  switch (v.state) {
    case "future":
      return [h("p", { class: "muted" }, `Reise steht an · ab ${hm(j.departure)}, an ${hm(j.arrival)}`)];
    case "waiting":
      return [
        h("p", { class: "headline" }, v.headline),
        h("p", { class: "muted" }, v.detail),
        h("div", { class: "row" },
          h("button", { type: "button", class: "btn small", onclick: (e) => checkOne(j.id, e.target.closest(".card")) }, "Verspätung prüfen"),
          h("button", { type: "button", class: "link", onclick: () => toggleArrival(j.id) }, "Ankunft selbst eintragen")),
        state.arrivalOpen.has(j.id) ? arrivalForm(j) : null,
      ];
    case "missing":
      return [
        h("p", { class: "headline" }, v.headline),
        h("p", { class: "muted" }, v.detail),
        h("div", { class: "row" },
          h("button", { type: "button", class: "btn", onclick: () => report(j, "ausfall") }, "Zug fiel aus"),
          h("button", { type: "button", class: "link", onclick: () => toggleArrival(j.id) }, "Ankunft selbst eintragen")),
        state.arrivalOpen.has(j.id) ? arrivalForm(j) : null,
      ];
    case "no_action":
      return [h("p", { class: "muted" }, h("b", {}, v.headline), " · ", v.detail), missedLink(j)];
    case "ask":
      return [
        h("p", { class: "question" }, v.question),
        h("div", { class: "answers" }, answer(j, "ja"), answer(j, "nein")),
        missedLink(j),
        reportedNote(j),
      ];
    case "needs_arrival":
      return [h("p", { class: "headline" }, v.headline), h("p", { class: "muted" }, v.detail), arrivalForm(j), changeAnswer(j)];
    case "choose":
      return [
        h("p", { class: "headline" }, v.headline, h("span", { class: "muted" }, ` ${v.detail}`)),
        h("div", { class: "options" },
          option(j, v.options[0], `Geld zurück: ${eur(v.options[0].amount_eur)}`, "Erstattung wählen", "erstattung"),
          h("span", { class: "or", "aria-hidden": "true" }, "oder"),
          option(j, v.options[1], `Später fahren: gültig bis ${de(v.reuse_limit)}`, "In den Vorrat", "vorrat")),
        changeAnswer(j),
      ];
    case "claim":
      return claimBody(j);
    case "claimed":
      return [
        h("p", { class: "headline" }, `Beantragt${j.claim_date ? ` am ${de(j.claim_date)}` : ""} · ${eur(v.amount_eur)}`),
        h("div", { class: "row" },
          h("span", { class: "muted" }, "Ausgang:"),
          h("button", { type: "button", class: "btn small", onclick: () => paid(j) }, "Ausgezahlt"),
          h("button", { type: "button", class: "btn small", onclick: () => save(j.id, { claim_status: "abgelehnt" }) }, "Abgelehnt")),
      ];
    case "reuse":
      return reuseBody(j);
    case "none":
      return [
        h("p", { class: "headline" }, v.headline),
        h("p", { class: "muted" }, v.detail, " ", ruleLink(v.rule)),
        j.ridden === "ja" ? otherArrival(j) : null,
        missedLink(j),
        changeAnswer(j),
      ];
    default:
      return [h("p", { class: "muted" }, h("b", {}, v.headline), v.detail ? ` · ${v.detail}` : "")];
  }
}

function answer(j, key) {
  const a = j.verdict.answers[key];
  return h("div", { class: "answer" },
    h("button", { type: "button", class: `answer-btn kind-${a.kind}`, onclick: () => save(j.id, { ridden: key }) },
      h("span", { class: "answer-key" }, `${j.verdict.answer_keys[key]} →`), h("span", { class: "answer-value" }, a.label),
      a.also ? h("span", { class: "answer-also" }, a.also) : null),
    a.note ? h("p", { class: "note" }, a.note) : null,
    a.condition ? h("p", { class: "condition" }, a.condition) : null,
    a.force_majeure ? forceMajeure() : null,
    a.force_majeure ? null : h("p", { class: "note" }, ruleLink(a.rule)),
  );
}

function option(j, o, title, action, choice) {
  return h("div", { class: "option" },
    h("p", { class: "option-title" }, title),
    h("p", { class: "note" }, o.note),
    o.condition ? h("p", { class: "condition" }, o.condition) : null,
    h("button", { type: "button", class: "btn primary", onclick: () => save(j.id, { choice }) }, action),
    h("p", { class: "note" }, ruleLink(o.rule)),
  );
}

function claimBody(j) {
  const v = j.verdict;
  const comp = v.claim_kind === "entschaedigung";
  return [
    h("p", { class: "amount" }, h("span", { class: "amount-label" }, comp ? "Entschädigung" : "Erstattung"), h("span", { class: "amount-value" }, eur(v.amount_eur))),
    h("p", { class: "note" }, v.detail),
    h("div", { class: "row" },
      h("button", { type: "button", class: "btn primary", onclick: () => openClaim(j.id) }, comp ? "Entschädigung beantragen" : "Erstattung beantragen"),
      comp && v.evidence ? h("button", { type: "button", class: "btn", onclick: () => copyEvidence(j) }, "Nachweis kopieren") : null,
      calendarLinks(j)),
    comp ? forceMajeure() : h("p", { class: "note" }, ruleLink(v.rule)),
    comp ? otherArrival(j) : null,
    changeAnswer(j),
  ];
}

function reuseBody(j) {
  const v = j.verdict;
  return [
    h("p", { class: "amount" }, h("span", { class: "amount-label" }, "Im Vorrat"), h("span", { class: "amount-value small" }, `gültig bis ${de(v.reuse_until)}`)),
    h("p", { class: "note" }, v.detail, " ", ruleLink("zugbindung")),
    h("div", { class: "row" },
      j.has_pdf ? h("a", { class: "btn primary", href: `/proof/${j.id}.pdf`, download: j.proof_filename }, "PDF herunterladen") : null,
      calendarLinks(j),
      h("button", { type: "button", class: "btn", onclick: () => used(j) }, "Ticket genutzt")),
    j.has_pdf ? h("p", { class: "hint" }, "Tipp: Auf dem Handy in Dateien/Drive speichern, nicht nur im Chat lassen.") : null,
    changeAnswer(j),
  ];
}

function calendarLinks(j) {
  return h("span", { class: "cal" },
    h("a", { class: "btn", href: `/ics/${j.id}.ics`, download: "" }, "In Kalender"),
    j.google_calendar_url ? h("a", { class: "link small", href: j.google_calendar_url, target: "_blank", rel: "noopener noreferrer" }, "Google Kalender ↗") : null);
}

function otherArrival(j) {
  return h("div", { class: "other-arrival" },
    h("button", { type: "button", class: "link small", onclick: () => toggleArrival(j.id) }, j.manual_arrival ? `Ankunft laut dir: ${de(j.manual_arrival)} ${hm(j.manual_arrival)} – ändern` : "Anders angekommen?"),
    state.arrivalOpen.has(j.id) ? arrivalForm(j) : null);
}

function arrivalForm(j) {
  const input = h("input", { type: "datetime-local", name: "manual_arrival", value: j.manual_arrival ? j.manual_arrival.slice(0, 16) : "", required: true });
  return h("form", { class: "arrival", onsubmit: async (e) => {
      e.preventDefault();
      state.arrivalOpen.delete(j.id);
      await save(j.id, { manual_arrival: input.value, ...(j.ridden ? {} : { ridden: "ja" }) });
    } },
    h("label", {}, "Deine Ankunft am Ziel", input),
    h("button", { class: "btn small primary" }, "Speichern"),
    j.manual_arrival ? h("button", { type: "button", class: "link small", onclick: () => save(j.id, { manual_arrival: "" }) }, "Eigene Angabe löschen") : null);
}

function missedLink(j) {
  if (!j.verdict.can_report_missed) return null;
  return h("p", { class: "note" },
    h("button", { type: "button", class: "link small", onclick: () => report(j, "anschluss") }, "Anschluss verpasst?"),
    " Auch bei kleiner Verspätung hebt ein verpasster Anschluss auf diesem Ticket die Zugbindung auf. ",
    ruleLink("anschluss"));
}

function reportedNote(j) {
  if (!j.reported) return null;
  const what = j.reported === "anschluss" ? "Anschluss verpasst" : "Zug fiel aus";
  return h("p", { class: "note" }, `Deine Angabe: ${what}. `,
    h("button", { type: "button", class: "link small", onclick: () => report(j, "") }, "zurücknehmen"));
}

async function report(j, what) {
  try {
    await afterUpdate(await call("report", j.id, what));
  } catch (err) {
    toast(err.message, true);
  }
}

function changeAnswer(j) {
  if (!j.ridden) return null;
  return h("button", { type: "button", class: "link small change", onclick: () => call("reset_answer", j.id).then(afterUpdate) }, "Antwort ändern");
}

function details(j) {
  const v = j.verdict;
  const cfg = state.config;
  const select = (name, options, value) => h("select", { name }, ...Object.entries(options).map(([k, label]) => h("option", { value: k, selected: k === value }, label)));
  const priceText = j.price_basis !== j.price ? `${eur(j.price)} · Basis ${eur(j.price_basis)} (${j.label})` : eur(j.price);
  return h("section", { class: "details" },
    h("ul", { class: "legs" }, ...j.legs.map(legRow)),
    h("dl", { class: "facts" },
      h("dt", {}, "Auftrag"), h("dd", {}, j.order_number),
      h("dt", {}, "Tarif"), h("dd", {}, [j.fare, j.travel_class ? `${j.travel_class}. Klasse` : null, j.trip_kind].filter(Boolean).join(" · ")),
      h("dt", {}, "Preis"), h("dd", {}, priceText),
      v.claim_limit && v.due_kind === "claim" ? [h("dt", {}, "Frist DB"), h("dd", {}, `Anträge laut bahn.de bis ${de(v.claim_limit)} `, ruleLink("frist"))] : null,
    ),
    v.zugbindung_aufgehoben ? h("p", {}, h("span", { class: "badge teal" }, "Zugbindung aufgehoben")) : null,
    v.evidence ? h("p", { class: "evidence" }, v.evidence, j.delays_checked ? ` Abgerufen am ${de(j.delays_checked)}${j.delays_final ? " (endgültig)" : ""}.` : "") : null,
    ...v.warnings.map((w) => h("p", { class: "warning" }, w)),
    v.sources.length ? h("div", {}, h("p", { class: "label" }, "Quellen"),
      h("ul", { class: "sources" }, ...v.sources.map((k) => h("li", {}, h("a", { href: cfg.rules[k].source_url, target: "_blank", rel: "noopener noreferrer" }, `${cfg.rules[k].title} ↗`), " ", h("span", { class: "muted" }, cfg.rules[k].text))))) : null,
    h("form", { class: "inputs", onchange: (e) => onDetailChange(j, e) },
      h("label", {}, "Kontrolliert? (nur für dich)", select("controlled", cfg.controlled, j.controlled)),
      h("label", {}, "Antrag", select("claim_status", cfg.claim, j.claim_status)),
      j.claim_status ? h("label", {}, "Beantragt am", h("input", { type: "date", name: "claim_date", value: j.claim_date || "" })) : null,
      j.claim_status === "ausgezahlt" ? h("label", {}, "Ausgezahlt €", h("input", { type: "number", step: "0.01", min: "0", name: "claim_amount", value: j.claim_amount ?? "" })) : null,
      h("label", { class: "wide" }, "Notiz", h("input", { type: "text", name: "notes", value: j.notes || "", placeholder: "z. B. Vorgangsnummer, Ersatzzug" })),
    ),
    h("div", { class: "row" },
      j.has_pdf ? h("a", { class: "btn small", href: `/ticket/${j.order_number}.pdf`, target: "_blank", rel: "noopener" }, "Original-Ticket ↗") : null,
      dt(j.arrival) < new Date() ? h("button", { type: "button", class: "btn small", onclick: (e) => checkOne(j.id, e.target.closest(".card")) }, "Verspätung neu prüfen") : null,
      j.ridden ? h("button", { type: "button", class: "btn small", onclick: () => call("reset_answer", j.id).then(afterUpdate) }, "Antwort ändern") : null,
      h("span", { class: "spacer" }),
      h("button", { type: "button", class: "btn small danger", onclick: () => remove(j) }, "Löschen")),
  );
}

function legRow(leg) {
  const d = leg.delay;
  let status = null;
  if (d) {
    if (d.status === "pending") status = h("span", { class: "chip" }, "noch offen");
    else if (d.status === "not_found") status = h("span", { class: "chip", title: d.message || "" }, "keine Daten");
    else if (d.dep_cancelled || d.arr_cancelled) status = h("span", { class: "chip late" }, "ausgefallen");
    else {
      const m = d.delay_min ?? 0;
      status = h("span", { class: `chip ${m >= 20 ? "late" : ""}` }, m > 0 ? `an ${hm(d.arr_actual)} · +${m} min` : "pünktlich");
    }
  }
  return h("li", {}, h("span", { class: "train" }, leg.train), h("span", {}, `${leg.origin} ${hm(leg.departure)} → ${leg.destination} ${hm(leg.arrival)}`), status);
}

// --- actions -------------------------------------------------------------------------

async function afterUpdate(j) {
  replaceJourney(j);
  const data = await call("overview");
  state.journeys = data.journeys;
  state.summary = data.summary;
  render();
}

async function save(id, fields) {
  try {
    await afterUpdate(await call("update", id, fields));
  } catch (err) {
    toast(err.message, true);
  }
}

function onDetailChange(j, e) {
  const t = e.target;
  if (!t.name) return;
  let value = t.value;
  if (t.name === "claim_amount") value = value === "" ? "" : Number(value);
  const fields = { [t.name]: value };
  if (t.name === "claim_status" && value && !j.claim_date) fields.claim_date = todayIso();
  save(j.id, fields);
}

async function paid(j) {
  const input = prompt(`Ausgezahlter Betrag in € (leer lassen für ${eur(j.verdict.amount_eur)}):`, "");
  if (input === null) return;
  const amount = input.trim() ? Number(input.replace(",", ".")) : j.verdict.amount_eur;
  save(j.id, { claim_status: "ausgezahlt", claim_amount: Number.isFinite(amount) ? amount : "" });
}

async function used(j) {
  if (!confirm(`Ticket ${j.origin} → ${j.destination} als genutzt markieren? Es verlässt dann den Vorrat.`)) return;
  try {
    await afterUpdate(await call("mark_used", j.id));
  } catch (err) {
    toast(err.message, true);
  }
}

async function remove(j) {
  if (!confirm(`Auftrag ${j.order_number} mit allen Angaben löschen?`)) return;
  await call("delete_ticket", j.order_number);
  state.open.delete(j.id);
  await load();
}

function toggleDetails(id) {
  state.open.has(id) ? state.open.delete(id) : state.open.add(id);
  render();
}

function toggleArrival(id) {
  state.arrivalOpen.has(id) ? state.arrivalOpen.delete(id) : state.arrivalOpen.add(id);
  render();
}

function setTab(tab) {
  view.tab = tab;
  render();
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = h("textarea", { style: "position:fixed;opacity:0" }, text);
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

async function copyEvidence(j) {
  const text = `Auftrag ${j.order_number}, ${j.origin} → ${j.destination}, ${de(j.departure)}: ${j.verdict.evidence}`;
  toast((await copyText(text)) ? "Nachweis in die Zwischenablage kopiert." : text);
}

// --- claim assistant -----------------------------------------------------------------

const claim = { id: null, info: null, leftForBahn: false };

async function openClaim(id) {
  const info = await call("claim_info", id);
  Object.assign(claim, { id, info, leftForBahn: false });
  $("#claim-title").textContent = info.title;
  $("#claim-headline").textContent = info.headline;
  $("#claim-step").replaceChildren("Unter ", h("b", {}, "„Fahrgastrechte“"), info.kind === "erstattung" ? " den Antrag starten und angeben, dass du die Fahrt nicht angetreten hast." : " → ", info.kind === "erstattung" ? "" : h("b", {}, "„Entschädigung beantragen“"), info.kind === "erstattung" ? "" : ".");
  $("#claim-open").href = info.claim_url;
  $("#claim-form").href = info.form_url;
  $("#claim-return").hidden = true;
  $("#claim-fields").replaceChildren(
    ...info.fields.flatMap(({ label, value }) => {
      const btn = h("button", { type: "button", class: "btn small" }, "Kopieren");
      btn.addEventListener("click", async () => {
        if (await copyText(value)) {
          btn.textContent = "✓ kopiert";
          setTimeout(() => (btn.textContent = "Kopieren"), 1500);
        }
      });
      return [h("dt", {}, label), h("dd", {}, value), btn];
    }),
  );
  $("#claim-dialog").showModal();
}

$("#claim-open").addEventListener("click", async () => {
  claim.leftForBahn = true;
  if (await copyText(claim.info.order_number)) toast(`Auftragsnummer ${claim.info.order_number} ist in der Zwischenablage.`);
});
$("#claim-copy-all").addEventListener("click", async () => {
  if (await copyText(claim.info.all_text)) toast("Alle Angaben in die Zwischenablage kopiert.");
});
$("#claim-done").addEventListener("click", async () => {
  if (!claim.id) return;
  const j = await call("mark_claimed", claim.id);
  $("#claim-dialog").close();
  await afterUpdate(j);
  toast("Als beantragt markiert.");
});
window.addEventListener("focus", () => {
  if (claim.leftForBahn && $("#claim-dialog").open) $("#claim-return").hidden = false;
});

// --- about ---------------------------------------------------------------------------

$("#about-open").addEventListener("click", () => {
  const cfg = state.config;
  $("#about-version").textContent = cfg.version;
  $("#about-verified").textContent = `(geprüft am ${de(cfg.last_verified)})`;
  $("#about-rules").replaceChildren(
    ...Object.values(cfg.rules).map((r) =>
      h("li", {}, r.source_url ? h("a", { href: r.source_url, target: "_blank", rel: "noopener noreferrer" }, `${r.title} ↗`) : h("b", {}, r.title), " ", h("span", { class: "muted" }, r.text))),
  );
  $("#about-dialog").showModal();
});

// --- quit ----------------------------------------------------------------------------

$("#quit").addEventListener("click", async () => {
  if (!confirm("Ticketdepot beenden? Deine Daten bleiben gespeichert.")) return;
  try {
    await call("quit");
  } catch {
    /* the server may already be gone */
  }
  document.body.replaceChildren(
    h("main", { class: "ended" },
      h("h1", {}, "Ticketdepot ist beendet."),
      h("p", { class: "muted" }, "Du kannst dieses Fenster schließen. Zum Weitermachen die App wieder starten."),
    ),
  );
});

// --- delays ----------------------------------------------------------------------------

async function checkOne(id, el) {
  el?.classList.add("busy");
  try {
    replaceJourney(await call("check", id));
  } catch (err) {
    toast(`Abruf fehlgeschlagen: ${err.message}`, true);
  }
  const data = await call("overview");
  state.journeys = data.journeys;
  state.summary = data.summary;
  render();
}

async function checkDue(ids) {
  const button = $("#check-all");
  button.disabled = true;
  const progress = $("#progress");
  progress.hidden = false;
  let n = 0;
  for (const id of ids) {
    progress.textContent = `Verspätungen werden abgerufen … ${++n}/${ids.length} (ca. 20–60 s je Fahrt)`;
    await checkOne(id, $(`.card[data-id="${id}"]`));
  }
  progress.hidden = true;
  button.disabled = false;
}

$("#check-all").addEventListener("click", async () => {
  const ids = await call("due_checks");
  if (!ids.length) return toast("Alle Verspätungsdaten sind aktuell.");
  checkDue(ids);
});

// --- import ------------------------------------------------------------------------------

$("#scan").addEventListener("click", async () => {
  const res = await call("import_downloads");
  toast(res.message, !res.ok);
  await load();
  startDueChecks();
});

$("#file").addEventListener("change", async (e) => {
  await importFiles([...e.target.files]);
  e.target.value = "";
});

async function importFiles(files) {
  for (const file of files) {
    const b64 = await new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(r.result.split(",")[1]);
      r.onerror = reject;
      r.readAsDataURL(file);
    });
    const res = await call("import_pdf", file.name, b64);
    toast(res.message, !res.ok);
  }
  await load();
  startDueChecks();
}

let dragDepth = 0;
window.addEventListener("dragenter", (e) => {
  if (![...(e.dataTransfer?.types || [])].includes("Files")) return;
  dragDepth++;
  $("#drop").hidden = false;
});
window.addEventListener("dragleave", () => {
  if (--dragDepth <= 0) $("#drop").hidden = true;
});
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  $("#drop").hidden = true;
  const pdfs = [...e.dataTransfer.files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
  if (pdfs.length) importFiles(pdfs);
});

// --- filter controls -------------------------------------------------------------------------

$(".tabs").addEventListener("click", (e) => {
  const tab = e.target.closest("[data-tab]");
  if (tab) setTab(tab.dataset.tab);
});
$("#filter-toggle").addEventListener("click", () => {
  state.filtersOpen = !state.filtersOpen;
  render();
});
let searchTimer;
$("#search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    view.q = e.target.value.trim();
    render();
    $("#search").focus();
  }, 200);
});
$("#route").addEventListener("input", (e) => {
  view[e.target.name] = e.target.value;
  render();
  const input = $(`#route [name="${e.target.name}"]`);
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
});
$("#route").addEventListener("submit", (e) => e.preventDefault());
$("#reset-filters").addEventListener("click", () => {
  Object.assign(view, { q: "", chip: "", band: "", frist: false, von: "", nach: "" });
  render();
});

function toast(message, error = false) {
  const el = h("div", { class: `toast${error ? " error" : ""}` }, message);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), error ? 9000 : 5000);
}

async function startDueChecks() {
  const ids = await call("due_checks");
  if (ids.length) checkDue(ids);
}

// Start: show the list, then fetch delays for trips that are over but not final yet.
load()
  .then(startDueChecks)
  .catch((err) => toast(err.message, true));
