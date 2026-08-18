type CacheEntry<T> = { value: T; expiresAt: number };

const TTL_MS = 60_000;
const store = new Map<string, CacheEntry<unknown>>();
const inflight = new Map<string, Promise<unknown>>();

export function cacheKey(parts: Array<string | number | undefined | null>): string {
  return parts
    .filter((p): p is string | number => p !== undefined && p !== null)
    .map((p) => String(p))
    .join(":");
}

export async function cachedFetch<T>(
  key: string,
  fetcher: () => Promise<T>,
): Promise<T> {
  const now = Date.now();
  const cached = store.get(key) as CacheEntry<T> | undefined;
  if (cached && cached.expiresAt > now) {
    return cached.value;
  }
  const pending = inflight.get(key);
  if (pending) {
    return pending as Promise<T>;
  }
  const promise = fetcher()
    .then((value) => {
      store.set(key, { value, expiresAt: now + TTL_MS });
      return value;
    })
    .finally(() => {
      inflight.delete(key);
    });
  inflight.set(key, promise);
  return promise;
}

export function invalidateCache(prefix?: string): void {
  if (!prefix) {
    store.clear();
    return;
  }
  for (const key of store.keys()) {
    if (key.startsWith(prefix)) store.delete(key);
  }
}