// fetch wrapper: adds the CSRF header to every state-changing request, sends cookies,
// normalises errors, and sends the user to sign-in when the session has ended.

import { loginUrl } from "./util.js";

const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

export class ApiError extends Error {
  constructor(message, status, fields = {}) {
    super(message);
    this.status = status;
    this.fields = fields;
  }
}

export async function api(url, { method = "GET", body, headers = {}, signal } = {}) {
  const opts = { method, credentials: "same-origin", headers: { Accept: "application/json", ...headers }, signal };
  if (method !== "GET" && method !== "HEAD") opts.headers["X-CSRF-Token"] = csrf();
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }

  const type = res.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await res.json().catch(() => ({})) : null;

  if (res.status === 401 && !url.includes("/auth/login")) {
    const next = encodeURIComponent(location.pathname + location.search);
    location.assign(`${loginUrl()}?reason=timeout&next=${next}`);
    throw new ApiError("Your session ended. Please sign in again.", 401);
  }
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : "Something went wrong. Try again.";
    throw new ApiError(detail, res.status, data?.fields || {});
  }
  return data ?? res;
}

export const get = (url, o) => api(url, { ...o, method: "GET" });
export const post = (url, body, o) => api(url, { ...o, method: "POST", body });
export const patch = (url, body, o) => api(url, { ...o, method: "PATCH", body });
export const put = (url, body, o) => api(url, { ...o, method: "PUT", body });
export const del = (url, o) => api(url, { ...o, method: "DELETE" });
