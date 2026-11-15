// Thin fetch wrapper for the /api backend. Role is sent via X-Role header.
const api = {
  base: "/api",
  role: "citizen",

  async request(method, path, body) {
    const res = await fetch(this.base + path, {
      method,
      headers: { "Content-Type": "application/json", "X-Role": this.role },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw Object.assign(new Error((data && data.detail) || res.statusText), { status: res.status, data });
    return data;
  },
  get(path) { return this.request("GET", path); },
  post(path, body) { return this.request("POST", path, body); },

  ws(path) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return new WebSocket(`${proto}://${location.host}${this.base}${path}`);
  },
};
