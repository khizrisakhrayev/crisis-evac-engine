// Citizen app (Module 1). All visible text via t(); API data inserted with textContent only.
(() => {
  "use strict";

  const BAKU = [40.392, 49.86];
  const REFRESH_MS = 5000;
  const OCC_AMBER = 70; // UI colour bands only (reroute threshold itself lives in backend config)
  const OCC_RED = 90;
  const TYPE_ICON = { shelter: "🛡️", park: "🌳", stadium: "🏟️", assembly_point: "⛺" };
  const HAZARD_ICON = { fire: "🔥", collapse: "🏚️", flood: "🌊", medical: "🚑" };

  const $ = (sel) => document.querySelector(sel);
  function el(tag, className, text) {
    const e = document.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  const state = {
    pos: storage.getJSON("pos"),          // {lat, lon}
    chosenShelterId: null,
    nearest: [],
    route: null,
    roads: [],
    zones: [],
    baselineKey: null,                    // (position, chosen shelter, role) of the current route baseline
    banner: null,
    dismissedSig: null,
    activeSos: storage.getJSON("activeSos"),
    seq: 0,
    inFlight: 0,
    lastErrorAt: 0,
    toast: null,
  };
  let map = null;
  let posMarker = null;
  let shelterLayer, routeLayer, closedLayer;
  let tiles = { isOffline: () => false };
  let toastTimer = null;

  // --- identity / role -------------------------------------------------------
  function citizenId() {
    let id = storage.get("citizenId");
    if (!id) {
      id = "c-" + (window.crypto && crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2));
      storage.set("citizenId", id);
    }
    return id;
  }
  const isPriority = () => getRole() === "priority_citizen";

  function setRole(role) {
    storage.set("role", role);
    state.chosenShelterId = null;
    renderProfile();
    refresh();
  }

  // --- formatting ------------------------------------------------------------
  const locale = () => (LANG === "az" ? "az-Latn-AZ" : "en-GB");
  function fmtDistance(m) {
    if (m === null || m === undefined) return "—";
    if (m < 1000) return t("dist.m", { n: Math.round(m) });
    return t("dist.km", { n: (m / 1000).toLocaleString(locale(), { maximumFractionDigits: 1 }) });
  }
  function occClass(pct) {
    return pct >= OCC_RED ? "occ-red" : pct >= OCC_AMBER ? "occ-amber" : "occ-green";
  }
  const typeLabel = (type) => (hasKey(`type.${type}`) ? t(`type.${type}`) : type);

  // --- toast / errors ----------------------------------------------------------
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
  function showError(err, fromPolling = false) {
    const code = (err && err.code) || "generic";
    if (fromPolling) { // don't spam the user every 5 s while offline
      if (Date.now() - state.lastErrorAt < 15000) return;
      state.lastErrorAt = Date.now();
    }
    if (!(err && err.code)) console.warn(err);
    showToast(hasKey(`error.${code}`) ? `error.${code}` : "error.generic", null, true);
  }

  // --- map ---------------------------------------------------------------------
  function initMap() {
    map = L.map("map").setView(BAKU, 12);
    tiles = addResilientTiles(map, () => renderMapLayers()); // no tiles -> roads drawn as vector base map
    closedLayer = L.layerGroup().addTo(map);
    routeLayer = L.layerGroup().addTo(map);
    shelterLayer = L.layerGroup().addTo(map);
    map.on("click", (e) => setPosition(e.latlng.lat, e.latlng.lng));
    // Container height changes with the layout breakpoint; keep Leaflet's size in sync.
    if (window.ResizeObserver) new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById("map"));
  }

  function renderPosition() {
    if (!map) return;
    if (!state.pos) { if (posMarker) posMarker.remove(); posMarker = null; return; }
    const ll = [state.pos.lat, state.pos.lon];
    if (!posMarker) {
      posMarker = L.circleMarker(ll, {
        radius: 10, color: "#ffffff", weight: 3, fillColor: "#0d47a1", fillOpacity: 1, bubblingMouseEvents: false,
      }).addTo(map);
    }
    posMarker.setLatLng(ll);
    posMarker.unbindTooltip().bindTooltip(el("span", null, t("location.you")));
  }

  function renderMapLayers() {
    if (!map) return;
    closedLayer.clearLayers();
    if (tiles.isOffline()) { // offline base map: every road as a thin vector line
      for (const r of state.roads) {
        if (r.is_closed) continue;
        L.polyline([[r.from_lat, r.from_lon], [r.to_lat, r.to_lon]], {
          color: "#6b7280", weight: 3, opacity: 0.8, interactive: false,
        }).addTo(closedLayer);
      }
    }
    for (const r of state.roads) {
      if (!r.is_closed) continue;
      L.polyline([[r.from_lat, r.from_lon], [r.to_lat, r.to_lon]], {
        color: "#b71c1c", weight: 5, dashArray: "10 8", interactive: false,
      }).addTo(closedLayer);
    }
    routeLayer.clearLayers();
    const route = state.route;
    if (route && route.path && route.path.length > 1) {
      L.polyline(route.path, { color: "#0d47a1", weight: 6, opacity: 0.9, interactive: false }).addTo(routeLayer);
    }
    shelterLayer.clearLayers();
    const shown = [...state.nearest];
    if (route && route.shelter && !shown.some((s) => s.id === route.shelter.id)) shown.push(route.shelter);
    for (const s of shown) {
      const isTarget = route && route.shelter && route.shelter.id === s.id;
      const colour = s.occupancy_pct >= OCC_RED ? "#b71c1c" : s.occupancy_pct >= OCC_AMBER ? "#f59e0b" : "#1b7f3b";
      const m = L.circleMarker([s.lat, s.lon], {
        radius: isTarget ? 13 : 9, color: isTarget ? "#0d47a1" : "#111827", weight: isTarget ? 4 : 2,
        fillColor: colour, fillOpacity: 0.95, bubblingMouseEvents: false,
      });
      m.bindTooltip(el("span", null, `${TYPE_ICON[s.type] || "📍"} ${s.name}`));
      m.on("click", () => chooseShelter(s.id));
      m.addTo(shelterLayer);
    }
  }

  function fitRoute() {
    if (!map || !state.route || !state.route.path || state.route.path.length < 2) return;
    map.fitBounds(L.latLngBounds(state.route.path), { padding: [40, 40], maxZoom: 16 });
  }

  // --- position ------------------------------------------------------------------
  function setPosition(lat, lon) {
    state.pos = { lat: +lat.toFixed(6), lon: +lon.toFixed(6) };
    storage.setJSON("pos", state.pos);
    state.chosenShelterId = null;
    renderPosition();
    refresh();
  }

  function locateMe() {
    if (!navigator.geolocation) { showToast("error.geolocation", null, true); return; }
    showToast("location.locating");
    navigator.geolocation.getCurrentPosition(
      (p) => { setPosition(p.coords.latitude, p.coords.longitude); if (map) map.setView([p.coords.latitude, p.coords.longitude], 14); },
      () => showToast("error.geolocation", null, true),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    );
  }

  function chooseShelter(id) {
    state.chosenShelterId = id;
    refresh();
  }

  // --- refresh + automatic alternative --------------------------------------------
  const requestKey = () => JSON.stringify([state.pos, state.chosenShelterId, getRole()]);
  const routeSig = (r) => JSON.stringify([r && r.shelter ? r.shelter.id : null, r ? r.path : null]);

  async function refresh() {
    if (!state.pos) { renderAll(); return; }
    const seq = ++state.seq;
    state.inFlight += 1;
    const key = requestKey();
    const { lat, lon } = state.pos;
    const routeQs = `from_lat=${lat}&from_lon=${lon}` + (state.chosenShelterId ? `&shelter_id=${state.chosenShelterId}` : "");
    try {
      const [nearest, route, roads] = await Promise.all([
        api(`/shelters/nearest?lat=${lat}&lon=${lon}&limit=5`),
        api(`/route?${routeQs}`),
        api("/roads"),
      ]);
      if (seq !== state.seq) return; // a newer request superseded this one
      const payloadSig = JSON.stringify([key, nearest, route, roads]);
      if (payloadSig === state.payloadSig) return; // nothing changed: keep DOM (focus, taps) untouched
      state.payloadSig = payloadSig;
      const routeChanged = routeSig(state.route) !== routeSig(route);
      const isNewBaseline = updateBanner(key, route);
      state.nearest = nearest;
      state.route = route;
      state.roads = roads;
      renderAll();
      if (isNewBaseline || routeChanged) fitRoute();
    } catch (err) {
      if (seq === state.seq) showError(err, true);
    } finally {
      state.inFlight -= 1;
    }
  }

  // Banner: reason from the API, or route/target changed since the last refresh with the same request key.
  function updateBanner(key, route) {
    const sameBaseline = state.baselineKey === key && state.route !== null;
    const changed = sameBaseline && routeSig(state.route) !== routeSig(route);
    const shelterId = (r) => (r && r.shelter ? r.shelter.id : null);
    const targetChanged = route.original_shelter_id !== null && route.original_shelter_id !== undefined
      || (sameBaseline && shelterId(state.route) !== shelterId(route));
    state.baselineKey = key;
    if (!sameBaseline) { state.banner = null; state.dismissedSig = null; }
    if (!(route.reason || route.rerouted || changed)) return !sameBaseline;
    const sig = routeSig(route) + "|" + route.reason;
    if (state.dismissedSig === sig) return !sameBaseline;
    state.banner = {
      sig,
      danger: route.reason === "no_accessible_route",
      reason: route.reason,
      onlyChanged: !route.reason && !route.rerouted,
      target: route.shelter && targetChanged ? route.shelter.name : null, // only when the destination changed
    };
    return !sameBaseline;
  }

  // --- rendering --------------------------------------------------------------------
  function renderBanner() {
    const box = $("#banner");
    const b = state.banner;
    if (!b) { box.hidden = true; return; }
    box.classList.toggle("danger", b.danger);
    $("#banner-title").textContent = b.danger ? t("banner.danger") : b.onlyChanged ? t("banner.updated") : t("banner.rerouted");
    $("#banner-text").textContent = b.reason && hasKey(`reason.${b.reason}`) ? t(`reason.${b.reason}`) : "";
    $("#banner-target").textContent = b.target && !b.danger ? t("banner.new_target", { name: b.target }) : "";
    box.hidden = false;
  }

  function renderProfile() {
    document.querySelectorAll("[data-role]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.role === getRole())));
    $("#priority-badge").hidden = !isPriority();
  }

  function renderRoute() {
    const body = $("#route-body");
    body.replaceChildren();
    const route = state.route;
    if (!state.pos || !route) { body.append(el("p", "muted", t("route.empty"))); return; }
    if (!route.shelter) {
      body.append(el("p", "notice-danger", t(`reason.${route.reason || "no_accessible_route"}`)));
      return;
    }
    const dl = el("dl", "route-grid");
    const add = (labelKey, value) => { dl.append(el("dt", null, t(labelKey)), el("dd", null, value)); };
    add("route.target", `${TYPE_ICON[route.shelter.type] || "📍"} ${route.shelter.name}`);
    add("route.distance", fmtDistance(route.distance_m));
    add("route.eta", route.eta_min === null ? "—" : t("route.eta_value", { min: route.eta_min }));
    body.append(dl);
    if (route.accessible) body.append(el("span", "tag tag-ok", `♿ ${t("route.accessible")}`));
    if (route.provider) {
      const provider = hasKey(`provider.${route.provider}`) ? t(`provider.${route.provider}`) : route.provider;
      body.append(el("p", "small", t("route.via", { provider })));
    }
  }

  function renderNearest() {
    const list = $("#nearest-list");
    list.replaceChildren();
    if (!state.pos || state.nearest.length === 0) { list.append(el("li", "muted", t("nearest.empty"))); return; }
    const targetId = state.route && state.route.shelter ? state.route.shelter.id : null;
    for (const s of state.nearest) {
      const li = el("li");
      const btn = el("button", "shelter-item" + (s.id === targetId ? " selected" : ""));
      btn.type = "button";
      btn.addEventListener("click", () => chooseShelter(s.id));

      const head = el("div", "shelter-head");
      head.append(el("span", "shelter-name", `${TYPE_ICON[s.type] || "📍"} ${s.name}`));
      if (s.id === targetId) head.append(el("span", "tag tag-ok", t("nearest.selected")));
      btn.append(head);

      const meta = el("div", "shelter-meta");
      meta.append(el("span", null, typeLabel(s.type)), el("span", null, fmtDistance(s.distance_m)),
        el("span", null, t("nearest.occupancy", { pct: Math.round(s.occupancy_pct) })));
      if (s.is_full) meta.append(el("span", "tag tag-full", t("nearest.full")));
      if (s.is_accessible) {
        const acc = el("span", null, "♿");
        acc.title = t("nearest.accessible");
        acc.setAttribute("aria-label", t("nearest.accessible"));
        meta.append(acc);
      }
      btn.append(meta);

      const bar = el("div", "occ");
      const fill = el("span", occClass(s.occupancy_pct));
      fill.style.width = `${Math.min(100, s.occupancy_pct)}%`;
      bar.append(fill);
      btn.append(bar);

      li.append(btn);
      list.append(li);
    }
  }

  function renderDistricts() {
    const sel = $("#district-select");
    const current = sel.value;
    sel.querySelectorAll("option[data-zone]").forEach((o) => o.remove());
    for (const z of state.zones) {
      const o = el("option", null, z.name);
      o.value = String(z.id);
      o.dataset.zone = "1";
      sel.append(o);
    }
    sel.value = current;
  }

  function renderSos() {
    const s = state.activeSos;
    $("#sos-buttons").hidden = !!s;
    $("#sos-active").hidden = !s;
    if (!s) return;
    $("#sos-active-hazard").textContent = `${HAZARD_ICON[s.hazard_type] || "🆘"} ${t(`hazard.${s.hazard_type}`)}`;
    const time = new Date(s.created_at).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
    $("#sos-active-time").textContent = t("sos.sent_at", { time });
    const p = $("#sos-active-priority");
    p.textContent = t(`priority.${s.priority_label}`);
    p.className = s.priority_label === "critical" ? "prio-critical" : "";
  }

  function renderOfflineNotice() {
    // Persistent while routing is served from the local backup; disappears when the API is back online.
    $("#offline-notice").hidden = !(state.route && state.route.degraded);
  }

  function renderAll() {
    renderOfflineNotice();
    renderProfile();
    renderSos();
    renderBanner();
    renderRoute();
    renderNearest();
    renderToast();
    renderPosition();
    renderMapLayers();
  }

  // --- SOS -----------------------------------------------------------------------------
  async function sendSos(hazard) {
    if (!state.pos) { showToast("error.no_position", null, true); return; }
    const buttons = document.querySelectorAll(".sos-btn");
    buttons.forEach((b) => { b.disabled = true; });
    try {
      const s = await api("/sos", {
        method: "POST",
        body: { lat: state.pos.lat, lon: state.pos.lon, hazard_type: hazard, citizen_id: citizenId() },
      });
      state.activeSos = { id: s.id, hazard_type: s.hazard_type, created_at: s.created_at, priority_label: s.priority_label };
      storage.setJSON("activeSos", state.activeSos);
      renderSos();
      showToast("sos.sent");
    } catch (err) {
      showError(err);
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
    }
  }

  async function markSafe() {
    if (!state.activeSos) return;
    const btn = $("#safe-btn");
    btn.disabled = true;
    try {
      await api(`/sos/${state.activeSos.id}/safe`, { method: "POST" });
      clearSos();
      showToast("sos.safe_done");
    } catch (err) {
      if (err.code === "sos_not_found") clearSos(); else showError(err);
    } finally {
      btn.disabled = false;
    }
  }

  function clearSos() {
    state.activeSos = null;
    storage.remove("activeSos");
    renderSos();
  }

  async function verifyStoredSos() {
    if (!state.activeSos) return;
    try {
      const active = await api("/sos?status=active");
      if (!active.some((s) => s.id === state.activeSos.id)) clearSos();
    } catch (err) { /* keep local state when offline */ }
  }

  // --- init --------------------------------------------------------------------------------
  document.addEventListener("langchange", renderAll);

  document.addEventListener("DOMContentLoaded", async () => {
    initMap();
    document.querySelectorAll("[data-role]").forEach((b) => b.addEventListener("click", () => setRole(b.dataset.role)));
    document.querySelectorAll("[data-hazard]").forEach((b) => b.addEventListener("click", () => sendSos(b.dataset.hazard)));
    $("#safe-btn").addEventListener("click", markSafe);
    $("#locate-btn").addEventListener("click", locateMe);
    $("#banner-close").addEventListener("click", () => {
      if (state.banner) state.dismissedSig = state.banner.sig;
      state.banner = null;
      renderBanner();
    });
    $("#district-select").addEventListener("change", (e) => {
      const z = state.zones.find((zone) => String(zone.id) === e.target.value);
      if (z) { setPosition(z.center_lat, z.center_lon); map.setView([z.center_lat, z.center_lon], 14); }
    });

    renderAll();
    try {
      state.zones = await api("/zones");
      renderDistricts();
      state.roads = await api("/roads");
      renderMapLayers();
    } catch (err) {
      showError(err);
    }
    verifyStoredSos();
    if (state.pos) { map.setView([state.pos.lat, state.pos.lon], 14); refresh(); }
    setInterval(() => { if (state.inFlight === 0) refresh(); }, REFRESH_MS); // a slow call must not be superseded
  });
})();
