// Shared API helpers. X-Role: explicit {role} option > page override (api.role) > localStorage "role" > "citizen".

const storage = {
  get(key, fallback = null) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* storage unavailable */ } },
  remove(key) { try { localStorage.removeItem(key); } catch (e) { /* storage unavailable */ } },
  getJSON(key) { try { return JSON.parse(this.get(key)); } catch (e) { return null; } },
  setJSON(key, value) { this.set(key, JSON.stringify(value)); },
};

class ApiError extends Error {
  constructor(code, message, status) {
    super(message || code);
    this.code = code;       // language-neutral code, translate with t(`error.${code}`)
    this.status = status;   // HTTP status, 0 = network failure
  }
}

function getRole() {
  return api.role || storage.get("role", "citizen");
}

async function api(path, { method = "GET", body, role } = {}) {
  let res;
  try {
    res = await fetch("/api" + path, {
      method,
      headers: { "Content-Type": "application/json", "X-Role": role || getRole() },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError("network", e.message, 0);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const d = data && typeof data.detail === "object" ? data.detail : null;
    throw new ApiError((d && d.code) || `http_${res.status}`, (d && d.message) || res.statusText, res.status);
  }
  return data;
}
api.role = null; // pages may set a fixed role (e.g. dispatcher page)

function apiSocket(path) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${proto}://${location.host}/api${path}`);
}
