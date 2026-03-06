import "@testing-library/jest-dom/vitest";

function createStorageMock(): Storage {
  const store = new Map<string, string>();

  return {
    clear: () => {
      store.clear();
    },
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size;
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
  };
}

for (const key of ["localStorage", "sessionStorage"] as const) {
  if (typeof window[key]?.clear !== "function") {
    Object.defineProperty(window, key, {
      configurable: true,
      value: createStorageMock(),
    });
  }
}
