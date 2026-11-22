import { describe, expect, it, vi } from "vitest";
import { inWindow, pct, riskColor, usd, utc } from "../src/lib/display";
import {
  parseEvent,
  retryDelay,
  connectChannel,
} from "../src/ws/useLiveChannel";
import { coldStartCurve } from "../src/components/ColdStart";

describe("investigation controls", () => {
  it("maps both risk boundaries to their legend colors", () => {
    expect([0, 0.39, 0.4, 0.79, 0.8, 1].map(riskColor)).toEqual([
      "#67c6ba",
      "#67c6ba",
      "#efb961",
      "#efb961",
      "#f38072",
      "#f38072",
    ]);
  });
  it("includes transfers on either scrubber boundary", () => {
    const edges = [9, 10, 11, 12, 13].map((ts) => ({
      ts,
      src: 1,
      dst: 2,
      amount: 10,
      txn_id: ts,
      channel: "p2p",
    }));
    expect(inWindow(edges, 10, 12).map((e) => e.ts)).toEqual([10, 11, 12]);
  });
  it("formats currency, probability and UTC dates", () => {
    expect(usd(120000)).toBe("$120K");
    expect(pct(0.761)).toBe("76.1%");
    expect(utc(0)).toBe("1970-01-01");
  });
  it("displays only measured evaluation points and keeps zero AP", () => {
    expect(
      coldStartCurve({
        cold_start: { pr_auc: { 1: 0, 3: 0.34, 5: "invalid", 10: 1.1 } },
      }),
    ).toEqual([
      { step: 1, ap: 0 },
      { step: 3, ap: 0.34 },
    ]);
  });
});
describe("WebSocket protocol", () => {
  it("parses a typed crossing, consumes heartbeat, rejects unknown versions and malformed messages", () => {
    const event = {
      type: "account_scored",
      version: 1,
      payload: { account_id: 12, probability: 0.85 },
    };
    expect(parseEvent(JSON.stringify(event))).toMatchObject({
      id: 12,
      value: 85,
    });
    expect(
      parseEvent(
        JSON.stringify({
          type: "heartbeat",
          version: 1,
          ts: "2025-01-01T00:00:00Z",
        }),
      ),
    ).toBe("heartbeat");
    expect(parseEvent(JSON.stringify({ ...event, version: 2 }))).toBeNull();
    expect(parseEvent("oops")).toBeNull();
  });
  it("backs off on connection loss and caps the retry interval", () => {
    expect([0, 1, 2, 5, 6, 15].map(retryDelay)).toEqual([
      500, 1000, 2000, 16000, 30000, 30000,
    ]);
  });
});

it("reconnects after a lost socket, refreshes data, and stops retries on unmount", () => {
  vi.useFakeTimers();
  class TestSocket {
    static all: TestSocket[] = [];
    onopen?: () => void;
    onclose?: () => void;
    constructor() {
      TestSocket.all.push(this);
    }
    close() {
      this.onclose?.();
    }
  }
  vi.stubGlobal("WebSocket", TestSocket);
  vi.stubGlobal("window", globalThis);
  vi.stubGlobal("location", { protocol: "http:", host: "localhost" });
  try {
    const refresh = vi.fn(),
      disconnect = connectChannel("alerts", refresh);
    TestSocket.all[0]?.onclose?.();
    vi.advanceTimersByTime(499);
    expect(TestSocket.all).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(TestSocket.all).toHaveLength(2);
    TestSocket.all[1]?.onopen?.();
    expect(refresh).toHaveBeenCalledOnce();
    disconnect();
    vi.advanceTimersByTime(30000);
    expect(TestSocket.all).toHaveLength(2);
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});
