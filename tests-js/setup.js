import { afterEach } from "vitest";

// happy-dom doesn't provide localStorage in this config, so install a minimal
// in-memory Storage shim. The cards access it defensively (try/catch), but the
// persistence tests need a real round-trip to assert against.
class MemoryStorage {
  constructor() {
    this._data = new Map();
  }
  getItem(key) {
    return this._data.has(String(key)) ? this._data.get(String(key)) : null;
  }
  setItem(key, value) {
    this._data.set(String(key), String(value));
  }
  removeItem(key) {
    this._data.delete(String(key));
  }
  clear() {
    this._data.clear();
  }
}

if (typeof globalThis.localStorage === "undefined") {
  const storage = new MemoryStorage();
  globalThis.localStorage = storage;
  if (typeof window !== "undefined") {
    window.localStorage = storage;
  }
}

afterEach(() => {
  document.body.innerHTML = "";
  try {
    globalThis.localStorage.clear();
  } catch {
    /* no-op */
  }
});
