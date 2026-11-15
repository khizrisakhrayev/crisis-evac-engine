// Resilient base map: OSM tiles when the internet is available, otherwise a plain background with an
// "offline map" tag; pages draw roads from /api/roads as vector lines so the map stays usable.
const OSM_TILES = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";

function addResilientTiles(map, onChange) {
  const tag = document.createElement("div");
  tag.className = "map-offline-tag";
  tag.dataset.i18n = "map.offline";
  tag.textContent = t("map.offline");
  tag.hidden = true;
  map.getContainer().appendChild(tag);

  let loads = 0;
  let errors = 0;
  let offline = false;
  const set = (value) => {
    if (value === offline) return;
    offline = value;
    tag.hidden = !value;
    map.getContainer().classList.toggle("map-offline", value);
    if (onChange) onChange(value);
  };

  const layer = L.tileLayer(OSM_TILES, { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
  layer.on("tileload", () => { loads += 1; errors = 0; set(false); });
  layer.on("tileerror", () => { errors += 1; if (errors >= 2) set(true); });
  setTimeout(() => { if (loads === 0) set(true); }, 6000); // DNS/network hanging: no tile at all
  return { isOffline: () => offline };
}
