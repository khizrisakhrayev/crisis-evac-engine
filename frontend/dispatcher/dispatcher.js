// Dispatcher crisis dashboard (Module 2) + demo simulator (F3).
// Live data: overview refetch on every WebSocket event (throttled); polling fallback while the socket is down.
(() => {
  "use strict";

  const ROLE = "dispatcher";
  const dapi = (path, opts = {}) => api(path, { ...opts, role: opts.role || ROLE }); // never touches citizen's saved role

  const THROTTLE_MS = 500;
  const POLL_MS = 3000;
  const WS_MAX_BACKOFF_MS = 10000;
  const CONFIRMED_CARD_MS = 30000;
  // Display-only mirrors of backend config.py (backend changes are out of scope for the UI task).
  const CLUSTER_RADIUS_M = 500;
  const OCC_AMBER = 70;
  const OCC_RED = 90;
  const BAKU = [40.39, 49.86];
  const HAZARD = {
    fire: { icon: "🔥", color: "#ff7043" },
    collapse: { icon: "🏚️", color: "#bcaaa4" },
    flood: { icon: "🌊", color: "#29b6f6" },
    medical: { icon: "🚑", color: "#f06292" },
  };
  const TYPE_ICON = { shelter: "🛡️", park: "🌳", stadium: "🏟️", assembly_point: "⛺" };

  const $ = (sel) => document.querySelector(sel);
  function el(tag, className, text) {
    const e = document.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  const state = {
    ov: null, roads: [], zones: [], sig: null,
    seq: 0, lastFetch: 0, refreshTimer: null,
    ws: null, wsOpen: false, wsAttempts: 0, reconnectTimer: null, pollTimer: null, pollOk: null,
    confirming: new Set(), confirmed: [], simPoint: null, clickMode: "point", shelterOptionsSig: null, fitted: false, toast: null,
  };
  let map = null;
  const layers = {};
  let toastTimer = null;

  // --- helpers -----------------------------------------------------------------
  const locale = () => (LANG === "az" ? "az-Latn-AZ" : "en-GB");
  const zoneName = (id) => (state.zones.find((z) => z.id === id) || {}).name || "—";
  const zoneById = (id) => state.zones.find((z) => z.id === id);
  const shelterById = (id) => (state.ov ? state.ov.shelters.find((s) => s.id === id) : null);
  const brigadeById = (id) => (state.ov ? state.ov.brigades.find((b) => b.id === id) : null);
  const occColor = (pct) => (pct >= OCC_RED ? "#e53935" : pct >= OCC_AMBER ? "#ffb300" : "#43a047");
  const occClass = (pct) => (pct >= OCC_RED ? "occ-red" : pct >= OCC_AMBER ? "occ-amber" : "occ-green");
  const label = (prefix, code) => (hasKey(`${prefix}.${code}`) ? t(`${prefix}.${code}`) : code);
  const simOpen = () => $("#sim").open;

  function timeAgo(iso) {
    const mins = Math.floor((Date.now() - Date.parse(iso)) / 60000);
    return mins < 1 ? t("time.just_now") : t("time.min_ago", { n: mins });
  }
  const clock = (iso) => new Date(iso).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });

  function causeText(a) {
    if (a.kind === "shelter_overflow") {
      const s = shelterById(a.shelter_id);
      return t("alert.cause_overflow", { shelter: s ? s.name : "—", pct: s ? Math.round(s.occupancy_pct) : "—" });
    }
    return t("alert.cause_cluster", { zone: zoneName(a.zone_id), count: a.sos_count });
  }

  // --- toast / errors ------------------------------------------------------------
  function showToast(key, params, isError = false) {
    state.toast = { key, params, isError };
    renderToast();
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { state.toast = null; renderToast(); }, 4000);
  }
  function renderToast() {
    const box = $("#toast");
    if (!state.toast) { box.hidden = true; return; }
    box.textContent = t(state.toast.key, state.toast.params);
    box.classList.toggle("error", state.toast.isError);
    box.hidden = false;
  }
  function showError(err) {
    const code = (err && err.code) || "generic";
    if (err && err.status === 401) { logout(); return; }
    if (!(err && err.code)) console.warn(err);
    showToast(hasKey(`error.${code}`) ? `error.${code}` : "error.generic", null, true);
  }

  // --- data loading + live link ------------------------------------------------------
  async function load() {
    const seq = ++state.seq;
    state.lastFetch = Date.now();
    try {
      const [ov, roads] = await Promise.all([dapi("/dispatch/overview"), dapi("/roads")]);
      if (seq !== state.seq) return;
      state.pollOk = true;
      state.routingAt = Date.now();
      const sig = JSON.stringify([ov, roads]);
      if (sig !== state.sig) {
        state.sig = sig;
        state.ov = ov;
        state.roads = roads;
        render();
      }
      renderConn();
      if (!state.ws) { clearTimeout(state.reconnectTimer); state.reconnectTimer = null; connectWs(); } // server is back
    } catch (err) {
      if (seq !== state.seq) return;
      if (err.status === 401) { logout(); return; }
      state.pollOk = false;
      renderConn();
      if (err.code !== "network") showError(err);
    }
  }

  // At most one fetch per THROTTLE_MS; events during a fetch schedule a trailing one.
  function requestRefresh() {
    if (state.refreshTimer) return;
    const wait = Math.max(0, state.lastFetch + THROTTLE_MS - Date.now());
    state.refreshTimer = setTimeout(() => { state.refreshTimer = null; load(); }, wait);
  }

  function connectWs() {
    if (state.ws || !authToken.get()) return;
    let ws;
    try { ws = apiSocket("/ws/dispatch"); } catch (e) { scheduleReconnect(); return; }
    state.ws = ws;
    ws.onopen = () => {
      state.wsOpen = true;
      state.wsAttempts = 0;
      stopPolling();
      renderConn();
      requestRefresh();
    };
    ws.onmessage = () => requestRefresh();
    ws.onerror = () => { /* onclose follows */ };
    ws.onclose = () => {
      if (state.ws !== ws) return;
      state.ws = null;
      state.wsOpen = false;
      renderConn();
      if (!authToken.get()) return; // logged out
      startPolling();
      scheduleReconnect();
    };
  }
  function scheduleReconnect() {
    if (state.reconnectTimer) return;
    const delay = Math.min(WS_MAX_BACKOFF_MS, 1000 * 2 ** state.wsAttempts++);
    state.reconnectTimer = setTimeout(() => { state.reconnectTimer = null; connectWs(); }, delay);
  }
  function startPolling() { if (!state.pollTimer && authToken.get()) state.pollTimer = setInterval(load, POLL_MS); }

  // --- login / logout (JWT in sessionStorage) -----------------------------------------------
  function showLogin(errorKey) {
    $("#login").hidden = false;
    $("#logout").hidden = true;
    const e = $("#login-error");
    e.hidden = !errorKey;
    e.textContent = errorKey ? t(errorKey) : "";
    $("#login-user").focus();
  }
  function logout(expired = true) {
    authToken.clear();
    stopPolling();
    clearTimeout(state.reconnectTimer); state.reconnectTimer = null;
    clearTimeout(state.refreshTimer); state.refreshTimer = null;
    const ws = state.ws;
    state.ws = null; state.wsOpen = false;
    if (ws) try { ws.close(); } catch (e) { /* already closed */ }
    state.seq++;
    showLogin(expired ? "error.auth_required" : null);
  }
  async function start() {
    $("#login").hidden = true;
    $("#logout").hidden = false;
    try { state.zones = await dapi("/zones"); } catch (err) { showError(err); }
    await load();
    if (state.ov) { renderSimOptions(); syncSlider(); }
    connectWs();
  }
  function wireLogin() {
    $("#login-form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        const res = await api("/auth/login", { method: "POST",
          body: { username: $("#login-user").value.trim(), password: $("#login-pass").value } });
        authToken.set(res.access_token);
        $("#login-pass").value = "";
        start();
      } catch (err) {
        showLogin(hasKey(`error.${err.code}`) ? `error.${err.code}` : "error.generic");
      }
    });
    $("#logout").addEventListener("click", () => logout(false));
  }
  function stopPolling() { clearInterval(state.pollTimer); state.pollTimer = null; }

  // --- header chips ---------------------------------------------------------------------
  function renderConn() {
    const chip = $("#conn-chip");
    const [cls, key] = state.wsOpen ? ["chip-ok", "conn.connected"]
      : state.pollOk ? ["chip-warn", "conn.polling"] : ["chip-bad", "conn.reconnecting"];
    chip.className = `chip ${cls}`;
    chip.textContent = t(key);
  }
  function renderRouting() {
    const chip = $("#routing-chip");
    const r = state.ov && state.ov.routing;
    if (!r) { chip.hidden = true; return; }
    chip.hidden = false;
    const b = r.breaker;
    if (b.state === "open") {
      const left = Math.max(0, Math.ceil(b.seconds_until_retry - (Date.now() - (state.routingAt || Date.now())) / 1000));
      chip.className = "chip chip-bad";
      chip.textContent = t("breaker.open", { s: left });
    } else if (b.state === "half_open") {
      chip.className = "chip chip-warn";
      chip.textContent = t("breaker.half_open");
    } else if (r.mode === "fallback") { // API failing, breaker not tripped yet (it trips on route requests)
      chip.className = "chip chip-warn";
      chip.textContent = t("breaker.closed_failing");
    } else {
      chip.className = "chip chip-ok";
      chip.textContent = t("breaker.closed");
    }
    $("#sim-ext-up").setAttribute("aria-pressed", String(r.external_mode === "up"));
    $("#sim-ext-down").setAttribute("aria-pressed", String(r.external_mode === "down_503"));
    $("#sim-ext-slow").setAttribute("aria-pressed", String(r.external_mode === "slow"));
  }

  // --- red alert banner ---------------------------------------------------------------------
  function renderAlerts() {
    const area = $("#red-alerts");
    area.replaceChildren();
    if (!state.ov) return;
    for (const a of state.ov.alerts.filter((x) => x.status === "open")) {
      const card = el("div", "red-alert");
      const text = el("div");
      text.append(el("div", "official", t("alert.official")), el("div", "cause", causeText(a)));
      if (a.has_priority_sos) text.append(el("span", "tag tag-priority", t("alert.priority_involved")));
      const btn = el("button", "btn btn-confirm", t("alert.confirm"));
      btn.type = "button";
      btn.disabled = state.confirming.has(a.id);
      btn.addEventListener("click", () => confirmAlert(a.id));
      card.append(text, btn);
      area.append(card);
    }
    state.confirmed = state.confirmed.filter((c) => Date.now() - c.at < CONFIRMED_CARD_MS);
    for (const c of state.confirmed) {
      const card = el("div", "red-alert done");
      const text = el("div");
      text.append(el("div", "official", `✔ ${t("alert.confirmed")} — ${t("alert.official")}`));
      text.append(el("div", "cause", c.brigade ? t("alert.result_brigade", { name: c.brigade.name }) : t("alert.result_shortage")));
      text.append(el("div", "cause", t("alert.result_shelter", { name: c.shelter.name })));
      card.append(text);
      area.append(card);
    }
  }

  async function confirmAlert(id) {
    state.confirming.add(id);
    renderAlerts();
    try {
      const res = await dapi(`/dispatch/alerts/${id}/confirm`, { method: "POST" });
      state.confirmed.unshift({ at: Date.now(), alert: res.alert, brigade: res.brigade, shelter: res.shelter });
    } catch (err) {
      if (err.code !== "alert_already_confirmed") showError(err); // 409: someone else confirmed, just refresh
    } finally {
      state.confirming.delete(id);
      state.sig = null; // force a re-render with the fresh overview
      renderAlerts();
      requestRefresh();
    }
  }

  // --- KPIs -------------------------------------------------------------------------------------
  function setKpi(id, value, hot = false) {
    const box = $(id);
    box.querySelector(".value").textContent = value;
    box.classList.toggle("hot", hot);
  }
  function renderKpis() {
    const ov = state.ov;
    const openAlerts = ov.alerts.filter((a) => a.status === "open").length;
    const available = ov.brigades.filter((b) => b.status === "available").length;
    const open = ov.shelters.filter((s) => s.is_open);
    const avg = open.length ? open.reduce((sum, s) => sum + s.occupancy_pct, 0) / open.length : 0;
    setKpi("#kpi-active", String(ov.sos_total), ov.sos_total > 0);
    setKpi("#kpi-priority", String(ov.sos_priority_total), ov.sos_priority_total > 0);
    const sb = ov.spam_blocked;
    const blocked = sb.rate_limited + sb.duplicates + sb.suspected;
    setKpi("#kpi-flood", String(blocked), blocked > 0);
    $("#kpi-flood .sub").textContent = t("kpi.flood_detail", { a: sb.rate_limited, b: sb.duplicates, c: sb.suspected });
    setKpi("#kpi-alerts", String(openAlerts), openAlerts > 0);
    setKpi("#kpi-brigades", t("kpi.ratio", { a: available, b: ov.brigades.length }), available === 0);
    setKpi("#kpi-occupancy", t("kpi.pct", { n: Math.round(avg) }), avg >= OCC_RED);
  }

  // --- map --------------------------------------------------------------------------------------
  function initMap() {
    map = L.map("dmap").setView(BAKU, 12);
    addResilientTiles(map); // roads are always drawn as vectors, so the map works without tiles
    // Fixed drawing order regardless of re-render order.
    [["roads", 410], ["circles", 415], ["shelters", 420], ["brigades", 630], ["sos", 640], ["sim", 650]].forEach(([name, z]) => {
      map.createPane(name).style.zIndex = String(z);
      layers[name] = L.layerGroup().addTo(map);
    });
    map.on("click", (e) => { if (simOpen() && state.clickMode === "point") setSimPoint(e.latlng.lat, e.latlng.lng); });
    if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe($("#dmap"));
  }

  function renderMap() {
    if (!map || !state.ov) return;
    Object.values(layers).forEach((l) => l.clearLayers());
    const ov = state.ov;

    const roadMode = simOpen() && state.clickMode === "roads"; // wide hit lines only when toggling roads
    for (const r of state.roads) {
      const coords = r.geometry && r.geometry.length > 1 ? r.geometry : [[r.from_lat, r.from_lon], [r.to_lat, r.to_lon]];
      const style = r.is_closed ? { color: "#ff1744", weight: 5, dashArray: "10 8", opacity: 1 }
        : !r.is_accessible ? { color: "#9e9e9e", weight: 2, opacity: 0.8 }
        : { color: "#5c7cfa", weight: 3, opacity: 0.55 };
      L.polyline(coords, { ...style, pane: "roads", interactive: false }).addTo(layers.roads);
      if (!roadMode) continue;
      const hit = L.polyline(coords, { pane: "roads", weight: 18, opacity: 0.01, className: "road-hit", bubblingMouseEvents: false });
      hit.on("click", () => toggleRoad(r));
      hit.addTo(layers.roads);
    }

    for (const a of ov.alerts.filter((x) => x.status === "open" && x.kind === "sos_cluster")) {
      L.circle([a.lat, a.lon], {
        radius: CLUSTER_RADIUS_M, pane: "circles", color: "#ff5252", weight: 2, fillOpacity: 0.12, interactive: false,
      }).addTo(layers.circles);
    }

    for (const s of ov.shelters) {
      const closed = !s.is_open;
      const m = L.circleMarker([s.lat, s.lon], {
        pane: "shelters", className: "shelter", radius: 10, weight: 3, bubblingMouseEvents: false,
        color: closed ? "#9e9e9e" : "#ffffff", dashArray: closed ? "4 3" : null,
        fillColor: closed ? "#616161" : occColor(s.occupancy_pct), fillOpacity: closed ? 0.5 : 0.95,
      });
      m.bindTooltip(el("span", null, `${TYPE_ICON[s.type] || "📍"} ${s.name} · ${t("kpi.pct", { n: Math.round(s.occupancy_pct) })}`));
      m.on("click", () => { if (simOpen()) { $("#sim-shelter").value = String(s.id); syncSlider(); } });
      m.addTo(layers.shelters);
    }

    ov.brigades.forEach((b, i) => {
      const z = zoneById(b.status === "dispatched" && b.target_zone_id ? b.target_zone_id : b.zone_id);
      if (!z) return;
      const m = L.marker([z.center_lat + 0.0025 * ((i % 3) - 1), z.center_lon + 0.004 * ((i % 2) ? 1 : -1)], {
        pane: "brigades", keyboard: false,
        icon: L.divIcon({ className: "brigade-icon", html: b.status === "dispatched" ? "🚨" : "🚒", iconSize: [24, 24] }),
      });
      m.bindTooltip(el("span", null, `${b.name} · ${label("brigade", b.status)}`));
      m.addTo(layers.brigades);
    });

    for (const s of ov.sos) {
      const hz = HAZARD[s.hazard_type] || { icon: "🆘", color: "#ffffff" };
      const prio = s.priority === 1;
      if (prio) {
        L.circleMarker([s.lat, s.lon], { pane: "sos", radius: 16, color: "#ffeb3b", weight: 3, fill: false, interactive: false })
          .addTo(layers.sos);
      }
      const m = L.circleMarker([s.lat, s.lon], {
        pane: "sos", className: "sos", radius: prio ? 10 : 7, color: "#000000", weight: 2,
        fillColor: hz.color, fillOpacity: 1, bubblingMouseEvents: false,
      });
      m.bindTooltip(el("span", null, `${hz.icon} ${label("hazard", s.hazard_type)} · ${zoneName(s.zone_id)}`));
      m.addTo(layers.sos);
    }

    if (state.simPoint) {
      L.circleMarker([state.simPoint.lat, state.simPoint.lon], {
        pane: "sim", radius: 9, color: "#ffb300", weight: 3, fillOpacity: 0, dashArray: "3 3", interactive: false,
      }).addTo(layers.sim);
    }

    if (!state.fitted && ov.shelters.length) {
      state.fitted = true;
      const bounds = L.latLngBounds(ov.shelters.map((s) => [s.lat, s.lon]));
      requestAnimationFrame(() => { map.invalidateSize(); map.fitBounds(bounds, { padding: [30, 30] }); }); // after layout settles
    }
  }

  // --- panels ---------------------------------------------------------------------------------------
  function emptyItem(list) { list.append(el("li", "muted", t("panel.empty"))); }

  function renderSosFeed() {
    const list = $("#sos-feed");
    list.replaceChildren();
    if (!state.ov.sos.length) { emptyItem(list); return; }
    for (const s of state.ov.sos) {
      const hz = HAZARD[s.hazard_type] || { icon: "🆘" };
      const li = el("li", s.priority === 1 ? "prio" : "");
      li.append(el("span", "grow", `${hz.icon} ${label("hazard", s.hazard_type)}`));
      if (s.priority === 1) li.append(el("span", "tag tag-priority", label("priority", s.priority_label)));
      li.append(el("span", null, zoneName(s.zone_id)), el("span", "small", timeAgo(s.created_at)),
        el("span", "tag tag-muted", label("status", s.status)));
      list.append(li);
    }
  }

  function renderShelters() {
    const list = $("#shelter-list");
    list.replaceChildren();
    const items = [...state.ov.shelters].sort((a, b) => (b.is_open - a.is_open) || (b.occupancy_pct - a.occupancy_pct));
    for (const s of items) {
      const li = el("li");
      li.append(el("span", "grow", `${TYPE_ICON[s.type] || "📍"} ${s.name}`));
      if (!s.is_open) li.append(el("span", "tag tag-muted", t("shelter.closed")));
      if (s.is_reserve) li.append(el("span", "tag tag-muted", t("shelter.reserve")));
      if (s.is_temporary) li.append(el("span", "tag tag-muted", t("shelter.temporary")));
      if (s.is_accessible) {
        const acc = el("span", null, "♿");
        acc.title = t("nearest.accessible");
        li.append(acc);
      }
      li.append(el("span", "small", t("kpi.pct", { n: Math.round(s.occupancy_pct) })));
      const wrap = el("div", "occ-ticks");
      wrap.style.width = "100%";
      wrap.title = t("shelter.ticks");
      const bar = el("div", "occ");
      const fill = el("span", occClass(s.occupancy_pct));
      fill.style.width = `${Math.min(100, s.occupancy_pct)}%`;
      bar.append(fill);
      wrap.append(bar);
      li.append(wrap);
      list.append(li);
    }
  }

  function renderBrigades() {
    const list = $("#brigade-list");
    list.replaceChildren();
    for (const b of state.ov.brigades) {
      const li = el("li");
      li.append(el("span", "grow", `${b.status === "dispatched" ? "🚨" : "🚒"} ${b.name}`));
      li.append(el("span", `tag ${b.status === "dispatched" ? "tag-priority" : "tag-ok"}`, label("brigade", b.status)));
      li.append(el("span", "small", b.status === "dispatched"
        ? t("brigade.route", { home: zoneName(b.zone_id), target: zoneName(b.target_zone_id) }) : zoneName(b.zone_id)));
      if (b.status === "dispatched") {
        const btn = el("button", "btn", t("brigade.release"));
        btn.type = "button";
        btn.addEventListener("click", () => action(`/dispatch/brigades/${b.id}/release`));
        li.append(btn);
      }
      list.append(li);
    }
  }

  function renderZones() {
    const body = $("#zone-rows");
    body.replaceChildren();
    for (const z of state.ov.zones) {
      const tr = el("tr");
      tr.append(el("td", null, z.name), el("td", "num", String(z.active_sos)), el("td", "num", String(z.priority_sos)));
      body.append(tr);
    }
  }

  function renderHistory() {
    const list = $("#alert-history");
    list.replaceChildren();
    const done = state.ov.alerts.filter((a) => a.status === "confirmed");
    if (!done.length) { emptyItem(list); return; }
    for (const a of done) {
      const li = el("li");
      li.append(el("span", "grow", `${label("kind", a.kind)} · ${causeText(a)}`));
      li.append(el("span", "small", t("history.confirmed_at", { time: clock(a.confirmed_at) })));
      const brigade = brigadeById(a.brigade_id);
      li.append(el("span", null, brigade ? t("alert.result_brigade", { name: brigade.name }) : t("alert.result_shortage")));
      const shelter = shelterById(a.new_shelter_id);
      if (shelter) li.append(el("span", null, t("alert.result_shelter", { name: shelter.name })));
      list.append(li);
    }
  }

  // --- simulator ----------------------------------------------------------------------------------------
  function setSimPoint(lat, lon) {
    state.simPoint = { lat, lon };
    renderSimPoint();
    renderMap();
  }
  function simPoint() {
    if (state.simPoint) return state.simPoint;
    const c = map.getCenter();
    return { lat: c.lat, lon: c.lng };
  }
  function renderSimPoint() {
    const p = simPoint();
    $("#sim-point").textContent = t("sim.point", { lat: p.lat.toFixed(4), lon: p.lon.toFixed(4) });
  }
  function renderSimOptions() {
    const sel = $("#sim-shelter");
    const sig = JSON.stringify(state.ov.shelters.map((s) => [s.id, s.name]));
    if (sig === state.shelterOptionsSig) return; // keep the operator's selection while data refreshes
    const current = sel.value;
    sel.replaceChildren(...state.ov.shelters.map((s) => { const o = el("option", null, s.name); o.value = String(s.id); return o; }));
    if (current) sel.value = current;
    state.shelterOptionsSig = sig;
  }
  function renderSimMode() {
    $("#sim-mode-point").setAttribute("aria-pressed", String(state.clickMode === "point"));
    $("#sim-mode-roads").setAttribute("aria-pressed", String(state.clickMode === "roads"));
  }
  function syncSlider() {
    const s = shelterById(Number($("#sim-shelter").value));
    if (s) $("#sim-pct").value = String(Math.round(s.occupancy_pct));
    renderPctLabel();
  }
  function renderPctLabel() {
    $("#sim-pct-label").textContent = `${t("sim.occupancy")}: ${t("kpi.pct", { n: $("#sim-pct").value })}`;
  }

  async function action(path, opts = {}, doneKey = null, params = null) {
    try {
      const res = await dapi(path, { method: "POST", ...opts });
      if (doneKey) showToast(doneKey, typeof params === "function" ? params(res) : params);
      return res;
    } catch (err) {
      showError(err);
      return null;
    } finally {
      requestRefresh();
    }
  }

  function toggleRoad(r) {
    if (!simOpen() || state.clickMode !== "roads") return;
    action(`/roads/${r.id}/${r.is_closed ? "open" : "close"}`, {}, r.is_closed ? "sim.road_opened" : "sim.road_closed");
  }

  function wireSimulator() {
    $("#sim").addEventListener("toggle", () => { renderSimPoint(); renderMap(); });
    const setMode = (mode) => { state.clickMode = mode; renderSimMode(); renderMap(); };
    $("#sim-mode-point").addEventListener("click", () => setMode("point"));
    $("#sim-mode-roads").addEventListener("click", () => setMode("roads"));
    renderSimMode();
    $("#sim-burst").addEventListener("click", () => {
      const p = simPoint();
      const count = Math.max(1, Math.min(20, parseInt($("#sim-count").value, 10) || 4));
      action("/demo/sos-burst", { body: { lat: p.lat, lon: p.lon, count, hazard_type: $("#sim-hazard").value } },
        "sim.burst_done", (res) => ({ n: res.sos.length }));
    });
    $("#sim-priority").addEventListener("click", () => {
      const p = simPoint();
      const citizenId = "sim-prio-" + Math.random().toString(36).slice(2, 10);
      action("/sos", { role: "priority_citizen",
        body: { lat: p.lat, lon: p.lon, hazard_type: $("#sim-hazard").value, citizen_id: citizenId } }, "sos.sent");
    });
    $("#sim-shelter").addEventListener("change", syncSlider);
    $("#sim-pct").addEventListener("input", renderPctLabel);
    $("#sim-apply").addEventListener("click", () => {
      const s = shelterById(Number($("#sim-shelter").value));
      if (!s) return;
      const pct = Number($("#sim-pct").value);
      const current = Math.floor((pct * s.capacity) / 100); // floor: 95 % never rounds above the alert threshold
      action(`/shelters/${s.id}/occupancy`, { body: { current } }, "sim.done");
    });
    $("#sim-ext-up").addEventListener("click", () => action("/routing/external/up", {}, "sim.done"));
    $("#sim-ext-down").addEventListener("click", () => action("/routing/external/down", {}, "sim.done"));
    $("#sim-ext-slow").addEventListener("click", () => action("/routing/external/slow", {}, "sim.done"));
    $("#sim-reset").addEventListener("click", async () => {
      if (!window.confirm(t("sim.reset_confirm"))) return;
      state.confirmed = [];
      state.simPoint = null;
      await action("/demo/reset", {}, "sim.done");
    });
  }

  // --- render all ----------------------------------------------------------------------------------------
  function render() {
    renderConn();
    renderToast();
    if (!state.ov) return;
    renderRouting();
    renderAlerts();
    renderKpis();
    renderMap();
    renderSosFeed();
    renderShelters();
    renderBrigades();
    renderZones();
    renderHistory();
    renderSimOptions();
    if (map) renderSimPoint();
    renderPctLabel();
  }

  document.addEventListener("langchange", render);

  document.addEventListener("DOMContentLoaded", async () => {
    initMap();
    wireSimulator();
    wireLogin();
    renderConn();
    if (authToken.get()) start(); else showLogin(null);
    setInterval(() => { if (state.ov) { renderSosFeed(); renderAlerts(); } }, 15000); // time-ago + expire confirm cards
    setInterval(() => { if (state.ov && state.ov.routing.breaker.state === "open") renderRouting(); }, 1000); // countdown
  });
})();
