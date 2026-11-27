// Small fetch helpers. Every call throws an Error with a readable message on failure.

function qs(params = {}) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, v);
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function handle(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  if (!res.ok) {
    const msg = body?.error || body?.answer || body?.detail || `Request failed (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

export const api = {
  get: (path, params) => fetch(`/api/${path}${qs(params)}`).then(handle),
  post: (path, data) =>
    fetch(`/api/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {}),
    }).then(handle),
  upload: (file) => {
    const form = new FormData();
    form.append("file", file);
    return fetch("/api/import", { method: "POST", body: form }).then(handle);
  },
};

export const ACTIVE_STATUSES = ["pending", "discovering", "labelling"];

export const pct = (part, whole) => (whole ? Math.round((100 * part) / whole) : 0);
