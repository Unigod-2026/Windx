import { afterEach, describe, expect, it, vi } from "vitest";
import { cacheKey, cachedFetch, invalidateCache } from "./questionTabCache";

afterEach(() => {
  invalidateCache();
  vi.useRealTimers();
});

describe("cachedFetch", () => {
  it("returns cached value within TTL", async () => {
    const fetcher = vi.fn().mockResolvedValue("v1");
    expect(await cachedFetch("k1", fetcher)).toBe("v1");
    expect(await cachedFetch("k1", fetcher)).toBe("v1");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("dedupes in-flight requests", async () => {
    let resolve!: (v: string) => void;
    const fetcher = vi.fn().mockImplementation(
      () => new Promise<string>((r) => {
        resolve = r;
      }),
    );
    const p1 = cachedFetch("k2", fetcher);
    const p2 = cachedFetch("k2", fetcher);
    resolve("v2");
    expect(await p1).toBe("v2");
    expect(await p2).toBe("v2");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("re-fetches after TTL expiry", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn()
      .mockResolvedValueOnce("v3")
      .mockResolvedValueOnce("v4");
    expect(await cachedFetch("k3", fetcher)).toBe("v3");
    vi.advanceTimersByTime(61_000);
    expect(await cachedFetch("k3", fetcher)).toBe("v4");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("does not cache failures", async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce("v5");
    await expect(cachedFetch("k4", fetcher)).rejects.toThrow("boom");
    expect(await cachedFetch("k4", fetcher)).toBe("v5");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

describe("cacheKey", () => {
  it("joins parts with colon, drops nullish", () => {
    expect(cacheKey([1, "p", undefined, null, "x"])).toBe("1:p:x");
  });
});

describe("invalidateCache", () => {
  it("clears all entries when no prefix", async () => {
    const fetcher = vi.fn().mockResolvedValue("v6");
    await cachedFetch("k5", fetcher);
    invalidateCache();
    await cachedFetch("k5", fetcher);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("clears only matching prefix", async () => {
    const fetcher = vi.fn().mockResolvedValue("v7");
    await cachedFetch("summary:1", fetcher);
    await cachedFetch("product:1", fetcher);
    invalidateCache("summary");
    await cachedFetch("summary:1", fetcher);
    await cachedFetch("product:1", fetcher);
    expect(fetcher).toHaveBeenCalledTimes(3); // summary refetched, product cached
  });
});