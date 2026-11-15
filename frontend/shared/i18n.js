// All UI strings live here (az, en). Use t(key) in JS and data-i18n="key" in HTML.
const I18N = {
  az: {
    app_title: "Şəhər Böhranı və Evakuasiya",
    citizen_title: "Vətəndaş paneli",
    dispatcher_title: "Dispetçer paneli",
    go_dispatcher: "Dispetçer panelinə keç",
    go_citizen: "Vətəndaş panelinə keç",
    language: "Dil",
    placeholder: "Tezliklə...",
  },
  en: {
    app_title: "Urban Crisis & Evacuation",
    citizen_title: "Citizen view",
    dispatcher_title: "Dispatcher view",
    go_dispatcher: "Open dispatcher view",
    go_citizen: "Open citizen view",
    language: "Language",
    placeholder: "Coming soon...",
  },
};

let LANG = "az";
try { LANG = localStorage.getItem("lang") || "az"; } catch (e) { /* storage unavailable */ }

function t(key) {
  return (I18N[LANG] && I18N[LANG][key]) || I18N.en[key] || key;
}

function applyI18n(root = document) {
  document.documentElement.lang = LANG;
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  const titleEl = document.querySelector("title[data-i18n]");
  if (titleEl) document.title = t(titleEl.dataset.i18n);
}

function setLang(lang) {
  if (!I18N[lang]) return;
  LANG = lang;
  try { localStorage.setItem("lang", lang); } catch (e) { /* ignore */ }
  applyI18n();
}

document.addEventListener("DOMContentLoaded", () => {
  const sel = document.getElementById("lang-select");
  if (sel) {
    sel.value = LANG;
    sel.addEventListener("change", () => setLang(sel.value));
  }
  applyI18n();
});
