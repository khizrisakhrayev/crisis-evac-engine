// All UI strings live here (az, en). HTML: data-i18n / data-i18n-placeholder / data-i18n-aria.
// JS: t(key, {param}). API codes are translated via keys like `reason.road_closed`, `hazard.fire`.
const I18N = {
  az: {
    "app_title": "Şəhər Böhranı və Evakuasiya",
    "lang.az": "AZ",
    "lang.en": "EN",
    "lang.label": "Dil",
    "nav.citizen": "Vətəndaş paneli",
    "nav.dispatcher": "Dispetçer paneli",
    "citizen_title": "Vətəndaş paneli",
    "dispatcher_title": "Dispetçer paneli",
    "placeholder": "Tezliklə...",

    "profile.title": "Profil",
    "profile.citizen": "Vətəndaş",
    "profile.priority": "Hərəkət məhdudiyyətli və ya xüsusi qayğı tələb edən vətəndaş",
    "profile.badge": "Prioritet #1 · yalnız əlçatan marşrutlar",

    "sos.title": "Təcili SOS",
    "sos.hint": "Bir toxunuşla cari mövqeyiniz göndərilir",
    "sos.active_title": "SOS siqnalınız aktivdir",
    "sos.sent_at": "Göndərilib: {time}",
    "sos.safe_btn": "Mən təhlükəsizəm",
    "sos.sent": "SOS göndərildi",
    "sos.safe_done": "Təhlükəsiz kimi qeyd edildiniz",
    "hazard.fire": "Yanğın",
    "hazard.collapse": "Bina uçqunu",
    "hazard.flood": "Daşqın",
    "hazard.medical": "Tibbi yardım",
    "priority.critical": "Kritik prioritet #1",
    "priority.normal": "Adi prioritet",

    "location.title": "Mövqeyim",
    "location.use_mine": "Mövqeyimi təyin et",
    "location.district": "Rayon seçin",
    "location.hint": "Mövqeyinizi təyin etmək üçün xəritəyə toxunun",
    "location.you": "Siz buradasınız",
    "location.locating": "Mövqe müəyyənləşdirilir...",
    "map.label": "Bakı xəritəsi",

    "route.title": "Evakuasiya marşrutu",
    "route.empty": "Marşrut üçün mövqeyinizi təyin edin",
    "route.target": "Təyinat",
    "route.distance": "Məsafə",
    "route.eta": "Piyada vaxtı",
    "route.eta_value": "{min} dəq",
    "route.via": "Mənbə: {provider}",
    "route.accessible": "Əlçatan marşrut",
    "provider.external": "xarici xəritə xidməti",
    "provider.local-graph": "oflayn şəhər xəritəsi",
    "provider.straight-line": "düz xətt (təxmini)",
    "dist.m": "{n} m",
    "dist.km": "{n} km",

    "banner.rerouted": "Marşrut dəyişdi",
    "banner.updated": "Marşrut yeniləndi",
    "banner.danger": "Diqqət",
    "banner.new_target": "Yeni təyinat: {name}",
    "banner.dismiss": "Bağla",
    "reason.road_closed": "Yolunuzda bağlı yol var — alternativ marşrut verildi.",
    "reason.shelter_full": "Toplanma məntəqəsi doludur — sizi başqa məntəqəyə yönləndirdik.",
    "reason.shelter_not_accessible": "Seçilmiş məntəqə əlçatan deyil — əlçatan məntəqəyə yönləndirildiniz.",
    "reason.all_shelters_full": "Bütün məntəqələr doludur — ən yaxın məntəqəyə gedin.",
    "reason.no_accessible_route": "Əlçatan marşrut yoxdur. Tibbi nəqliyyat sorğusu göndərildi.",

    "nearest.title": "Ən yaxın toplanma məntəqələri",
    "nearest.empty": "Siyahını görmək üçün mövqeyinizi təyin edin",
    "nearest.pick_hint": "Marşrut üçün məntəqəyə toxunun",
    "nearest.full": "Dolu",
    "nearest.accessible": "Əlil arabası üçün əlçatan",
    "nearest.occupancy": "{pct}% dolu",
    "nearest.selected": "Marşrut",
    "type.shelter": "Sığınacaq",
    "type.park": "Park",
    "type.stadium": "Stadion",
    "type.assembly_point": "Müvəqqəti toplanma məntəqəsi",

    "error.network": "Serverlə əlaqə yoxdur",
    "error.generic": "Xəta baş verdi",
    "error.no_position": "Əvvəlcə mövqeyinizi təyin edin",
    "error.geolocation": "Mövqeyinizi müəyyən etmək mümkün olmadı",
    "error.validation_error": "Göndərilən məlumat düzgün deyil",
    "error.sos_not_found": "SOS tapılmadı",
    "error.shelter_not_found": "Məntəqə tapılmadı",
    "error.no_open_shelter": "Açıq toplanma məntəqəsi yoxdur",
    "error.unknown_district": "Naməlum rayon",
    "error.forbidden_role": "Bu əməliyyat üçün icazəniz yoxdur",
    "error.point_or_district_required": "Mövqe və ya rayon tələb olunur",
    "error.lat_lon_together": "Mövqe tam deyil",
    "error.road_not_found": "Yol tapılmadı",
    "error.alert_not_found": "Həyəcan siqnalı tapılmadı",
    "error.alert_already_confirmed": "Həyəcan siqnalı artıq təsdiqlənib",
    "error.brigade_not_found": "Briqada tapılmadı",
    "error.not_implemented": "Hələ hazır deyil",
  },
  en: {
    "app_title": "Urban Crisis & Evacuation",
    "lang.az": "AZ",
    "lang.en": "EN",
    "lang.label": "Language",
    "nav.citizen": "Citizen view",
    "nav.dispatcher": "Dispatcher view",
    "citizen_title": "Citizen view",
    "dispatcher_title": "Dispatcher view",
    "placeholder": "Coming soon...",

    "profile.title": "Profile",
    "profile.citizen": "Citizen",
    "profile.priority": "Mobility-impaired or special-care citizen",
    "profile.badge": "Priority #1 · accessible routes only",

    "sos.title": "Emergency SOS",
    "sos.hint": "One tap sends your current position",
    "sos.active_title": "Your SOS is active",
    "sos.sent_at": "Sent at {time}",
    "sos.safe_btn": "I am safe",
    "sos.sent": "SOS sent",
    "sos.safe_done": "You are marked as safe",
    "hazard.fire": "Fire",
    "hazard.collapse": "Building collapse",
    "hazard.flood": "Flood",
    "hazard.medical": "Medical",
    "priority.critical": "Critical priority #1",
    "priority.normal": "Normal priority",

    "location.title": "My position",
    "location.use_mine": "Use my location",
    "location.district": "Choose district",
    "location.hint": "Tap the map to set your position",
    "location.you": "You are here",
    "location.locating": "Locating...",
    "map.label": "Map of Baku",

    "route.title": "Evacuation route",
    "route.empty": "Set your position to get a route",
    "route.target": "Destination",
    "route.distance": "Distance",
    "route.eta": "Walking time",
    "route.eta_value": "{min} min",
    "route.via": "via {provider}",
    "route.accessible": "Accessible route",
    "provider.external": "external map service",
    "provider.local-graph": "offline city graph",
    "provider.straight-line": "straight line (approximate)",
    "dist.m": "{n} m",
    "dist.km": "{n} km",

    "banner.rerouted": "Route changed",
    "banner.updated": "Route updated",
    "banner.danger": "Attention",
    "banner.new_target": "New destination: {name}",
    "banner.dismiss": "Dismiss",
    "reason.road_closed": "A road on your path is closed — an alternative route was given.",
    "reason.shelter_full": "Your assembly point is full — you were redirected.",
    "reason.shelter_not_accessible": "That assembly point is not accessible — redirected to an accessible one.",
    "reason.all_shelters_full": "All assembly points are full — go to the nearest one.",
    "reason.no_accessible_route": "No accessible route. Medical transport has been requested.",

    "nearest.title": "Nearest assembly points",
    "nearest.empty": "Set your position to see assembly points",
    "nearest.pick_hint": "Tap an assembly point to route there",
    "nearest.full": "Full",
    "nearest.accessible": "Wheelchair accessible",
    "nearest.occupancy": "{pct}% full",
    "nearest.selected": "Route",
    "type.shelter": "Shelter",
    "type.park": "Park",
    "type.stadium": "Stadium",
    "type.assembly_point": "Temporary assembly point",

    "error.network": "No connection to the server",
    "error.generic": "Something went wrong",
    "error.no_position": "Set your position first",
    "error.geolocation": "Could not get your location",
    "error.validation_error": "Invalid data sent",
    "error.sos_not_found": "SOS not found",
    "error.shelter_not_found": "Assembly point not found",
    "error.no_open_shelter": "No open assembly point",
    "error.unknown_district": "Unknown district",
    "error.forbidden_role": "You are not allowed to do this",
    "error.point_or_district_required": "Position or district required",
    "error.lat_lon_together": "Position is incomplete",
    "error.road_not_found": "Road not found",
    "error.alert_not_found": "Alert not found",
    "error.alert_already_confirmed": "Alert already confirmed",
    "error.brigade_not_found": "Brigade not found",
    "error.not_implemented": "Not available yet",
  },
};

let LANG = "az";
try { LANG = localStorage.getItem("lang") || "az"; } catch (e) { /* storage unavailable */ }
if (!I18N[LANG]) LANG = "az";

function t(key, params) {
  let s = (I18N[LANG] && I18N[LANG][key]) ?? I18N.en[key] ?? key;
  if (params) for (const [k, v] of Object.entries(params)) s = s.split(`{${k}}`).join(String(v));
  return s;
}

function hasKey(key) {
  return key in I18N[LANG] || key in I18N.en;
}

function applyI18n(root = document) {
  document.documentElement.lang = LANG;
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  root.querySelectorAll("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
  const titleEl = document.querySelector("title[data-i18n]");
  if (titleEl) document.title = t(titleEl.dataset.i18n);
  document.querySelectorAll("[data-lang]").forEach((b) => {
    const on = b.dataset.lang === LANG;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
  });
  document.dispatchEvent(new CustomEvent("langchange", { detail: { lang: LANG } }));
}

function setLang(lang) {
  if (!I18N[lang]) return;
  LANG = lang;
  try { localStorage.setItem("lang", lang); } catch (e) { /* ignore */ }
  applyI18n();
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));
  applyI18n();
});
