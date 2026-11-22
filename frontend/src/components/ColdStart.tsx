import { useQuery } from "@tanstack/react-query";
import { api, read } from "../api/client";
import { isRecord } from "../lib/display";

export function coldStartCurve(
  metrics: unknown,
): { step: number; ap: number }[] {
  if (
    !isRecord(metrics) ||
    !isRecord(metrics.cold_start) ||
    !isRecord(metrics.cold_start.pr_auc)
  )
    return [];
  const points = metrics.cold_start.pr_auc;
  return [1, 3, 5, 10].flatMap((step) => {
    const value = points[String(step)];
    return typeof value === "number" &&
      Number.isFinite(value) &&
      value >= 0 &&
      value <= 1
      ? [{ step, ap: value }]
      : [];
  });
}
export function ColdStart({ count }: { count: number }) {
  const query = useQuery({
    queryKey: ["metrics"],
    queryFn: () => read(api.GET("/api/v1/mule/model/metrics")),
    enabled: count < 10,
  });
  if (count >= 10) return <p>{count.toLocaleString()} observed transfers</p>;
  const points = coldStartCurve(query.data);
  return (
    <section aria-label="Cold-start evaluation">
      <strong className="badge caution">Low confidence</strong>
      <p>
        {count} observed {count === 1 ? "transfer" : "transfers"}. Held-out
        ranking quality varies with account history.
      </p>
      {points.length > 0 && (
        <table>
          <caption>Cold-start PR-AUC</caption>
          <thead>
            <tr>
              <th>Transfers</th>
              {points.map((p) => (
                <th key={p.step}>{p.step}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>PR-AUC</th>
              {points.map((p) => (
                <td key={p.step}>{p.ap.toFixed(3)}</td>
              ))}
            </tr>
          </tbody>
        </table>
      )}
      {query.isPending && <p>Loading evaluation…</p>}
      {!query.isPending && !points.length && (
        <p>Cold-start metrics unavailable.</p>
      )}
      <a href="/api/v1/mule/model/metrics" target="_blank" rel="noreferrer">
        Model evaluation ↗
      </a>
    </section>
  );
}
