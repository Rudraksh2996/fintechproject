import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, read, useRings } from "../api/client";
import { ColdStart } from "../components/ColdStart";
import { Feedback } from "../components/Feedback";
import { inWindow, pct, usd, utc } from "../lib/display";
import MuleGraph from "../three/MuleGraph";

export default function Mule() {
  const [params, set] = useSearchParams(),
    ring = params.get("ring"),
    account = params.get("account"),
    id = Number(account);
  const rings = useRings(),
    [percent, setPercent] = useState(100),
    [playing, play] = useState(false),
    [k, setK] = useState(2);
  const graph = useQuery({
    queryKey: ["mule", "network", ring],
    queryFn: () =>
      ring === null
        ? read(
            api.GET("/api/v1/mule/graph/overview", {
              params: { query: { max_nodes: 200 } },
            }),
          )
        : read(
            api.GET("/api/v1/mule/rings/{ring_id}/graph", {
              params: { path: { ring_id: Number(ring) } },
            }),
          ),
  });
  const detail = useQuery({
    queryKey: ["mule", "account", id],
    enabled: account !== null,
    queryFn: () =>
      read(
        api.GET("/api/v1/mule/accounts/{account_id}", {
          params: { path: { account_id: id } },
        }),
      ),
  });
  const edges = graph.data?.links;
  const bounds = useMemo(
    () =>
      edges?.length
        ? ([
            Math.min(...edges.map((e) => e.ts)),
            Math.max(...edges.map((e) => e.ts)),
          ] as const)
        : ([0, 0] as const),
    [edges],
  );
  const until = Math.round(
    bounds[0] + ((bounds[1] - bounds[0]) * percent) / 100,
  );
  const links = useMemo(
    () => inWindow(edges ?? [], bounds[0], until),
    [edges, bounds, until],
  );
  const nodes = useMemo(() => {
    const ids = new Set(links.flatMap((e) => [e.src, e.dst]));
    return graph.data?.nodes.filter((n) => ids.has(n.account_id)) ?? [];
  }, [graph.data, links]);
  const trail = useQuery({
    queryKey: ["mule", "trail", id, k, bounds[0], until],
    enabled: account !== null && !!edges,
    queryFn: () =>
      read(
        api.GET("/api/v1/mule/accounts/{account_id}/trail", {
          params: {
            path: { account_id: id },
            query: { k, t0: bounds[0], t1: until },
          },
        }),
      ),
  });
  const marked = useMemo(
    () => new Set((trail.data ?? []).flatMap((t) => t.transfers)),
    [trail.data],
  );
  const bins = useMemo(() => {
    const v = Array<number>(24).fill(0);
    for (const e of edges ?? []) {
      const b = Math.min(
        23,
        Math.floor(
          (24 * (e.ts - bounds[0])) / Math.max(1, bounds[1] - bounds[0]),
        ),
      );
      v[b] = (v[b] ?? 0) + 1;
    }
    return v;
  }, [edges, bounds]);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setPercent((p) => Math.min(100, p + 2));
    }, 250);
    return () => {
      clearInterval(timer);
    };
  }, [playing]);
  useEffect(() => {
    if (percent >= 100) play(false);
  }, [percent]);
  const selected = detail.data,
    group = rings.data?.find((r) => String(r.community) === ring);
  return (
    <>
      <header>
        <h1>Mule explorer</h1>
        <label>
          Candidate ring{" "}
          <select
            value={ring ?? ""}
            onChange={(e) => {
              set(e.target.value ? { ring: e.target.value } : {});
              setPercent(100);
            }}
          >
            <option value="">Overview</option>
            {rings.data?.map((r) => (
              <option key={r.community} value={r.community}>
                Ring {r.community} · {r.risk.toFixed(1)}
              </option>
            ))}
          </select>
        </label>
      </header>
      {rings.error && <p role="alert">{rings.error.message}</p>}
      <div className="columns explorer">
        <section className="panel">
          <h2>
            Transfer network{" "}
            <small>
              {nodes.length} accounts · {links.length} transfers
            </small>
          </h2>
          <Feedback
            loading={graph.isPending}
            error={graph.error}
            empty={!edges?.length}
          >
            <MuleGraph
              nodes={nodes}
              links={links}
              highlight={marked}
              choose={(a) => {
                set(
                  ring ? { ring, account: String(a) } : { account: String(a) },
                );
              }}
            />
            <small>
              Risk probability &nbsp; <b className="teal">● &lt;40%</b> &nbsp;{" "}
              <b className="amber">● 40–80%</b> &nbsp;{" "}
              <b className="red">● ≥80%</b>
              {graph.data?.truncated ? " · capped graph" : ""}
            </small>
            <div className="hist">
              {bins.map((v, i) => (
                <div
                  key={i}
                  style={{
                    height: String(5 + (95 * v) / Math.max(1, ...bins)) + "%",
                    opacity: i / 24 <= percent / 100 ? 1 : 0.3,
                  }}
                  title={String(v) + " transfers"}
                />
              ))}
            </div>
            <label>
              Through {utc(until)}{" "}
              <input
                aria-label="Time window"
                type="range"
                min={0}
                max={100}
                value={percent}
                onChange={(e) => {
                  play(false);
                  setPercent(Number(e.target.value));
                }}
              />
            </label>
            <button
              onClick={() => {
                if (percent === 100) setPercent(0);
                play(!playing);
              }}
            >
              {playing ? "Pause" : "Play replay"}
            </button>
          </Feedback>
        </section>
        <section className="panel">
          <h2>Account forensics</h2>
          {account === null ? (
            <p className="notice">
              Select an account in the network to inspect its activity.
            </p>
          ) : (
            <Feedback loading={detail.isPending} error={detail.error}>
              {selected && (
                <>
                  <h3>Account {id}</h3>
                  <p>
                    {selected.account.type} · {usd(selected.account.volume)}{" "}
                    volume
                  </p>
                  <strong className="big">
                    {pct(selected.account.probability)}
                  </strong>
                  <small>GraphSAGE mule probability</small>
                  <ColdStart count={selected.observed_transfers} />
                  <label>
                    Money trail{" "}
                    <select
                      value={k}
                      onChange={(e) => {
                        setK(Number(e.target.value));
                      }}
                    >
                      {[1, 2, 3, 4, 5, 6].map((n) => (
                        <option key={n} value={n}>
                          {n} hops
                        </option>
                      ))}
                    </select>
                  </label>
                  <p>
                    {trail.error
                      ? trail.error.message
                      : String(marked.size) + " trail transfers"}
                  </p>
                  <p>
                    Counterparties in view:{" "}
                    {Array.from(
                      new Set(
                        links
                          .filter((e) => e.src === id || e.dst === id)
                          .map((e) => (e.src === id ? e.dst : e.src)),
                      ),
                    )
                      .slice(0, 12)
                      .join(", ") || "None"}
                  </p>
                  <details>
                    <summary>Features and infrastructure</summary>
                    <p>
                      Community {selected.community ?? "unassigned"} · Devices{" "}
                      {selected.devices.join(", ")} · IPs{" "}
                      {selected.ips.join(", ")}
                    </p>
                    <dl>
                      {Object.entries(selected.features).map(([key, value]) => (
                        <div key={key}>
                          <dt>{key}</dt>
                          <dd>
                            {typeof value === "number"
                              ? Number(value.toPrecision(4))
                              : JSON.stringify(value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </details>
                </>
              )}
            </Feedback>
          )}
          {group && (
            <p>
              Ring risk {group.risk.toFixed(1)} · Structural factor{" "}
              {pct(group.structural_factor)} · Shared infrastructure{" "}
              {pct(group.shared_infra_factor)}
            </p>
          )}
        </section>
      </div>
    </>
  );
}
