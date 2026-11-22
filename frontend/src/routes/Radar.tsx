import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, read, useRadar } from "../api/client";
import { useLive } from "../ws/useLiveChannel";
import { usd } from "../lib/display";
import { Feedback } from "../components/Feedback";
import RadarScene from "../three/RadarScene";

export default function Radar() {
  const [params, set] = useSearchParams(),
    id = Number(params.get("id")),
    feed = useRadar(),
    cache = useQueryClient();
  const pulse = useLive(
    (s) => s.events.find((e) => e.type === "cluster_alert")?.id ?? null,
  );
  const detail = useQuery({
    queryKey: ["insider", "alert", id],
    queryFn: () =>
      read(
        api.GET("/api/v1/insider/alerts/{alert_id}", {
          params: { path: { alert_id: id } },
        }),
      ),
    enabled: id > 0,
  });
  const action = useMutation({
    mutationFn: (status: "acknowledged" | "dismissed") =>
      read(
        api.PATCH("/api/v1/insider/alerts/{alert_id}", {
          params: { path: { alert_id: id } },
          body: { status },
        }),
      ),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["insider"] }),
  });
  const choose = (n: number) => {
    set({ id: String(n) });
  };
  const a = detail.data;
  return (
    <>
      <header>
        <h1>Insider cluster radar</h1>
      </header>
      <p>Research tool — not investment advice.</p>
      <Feedback
        loading={feed.isPending}
        error={feed.error}
        empty={!feed.data?.length}
      >
        <div className="columns">
          <section className="panel">
            <h2>Cluster constellation</h2>
            <div className="scene">
              <RadarScene
                alerts={feed.data ?? []}
                choose={choose}
                pulse={pulse}
              />
            </div>
            <small>
              Radius · conviction &nbsp; Angle · filing date &nbsp; Size ·
              purchase value
            </small>
          </section>
          <section className="panel">
            <h2>Alert feed</h2>
            <div className="scroll">
              {[...(feed.data ?? [])].reverse().map((r) => (
                <button
                  className="event"
                  key={r.id}
                  onClick={() => {
                    choose(r.id);
                  }}
                >
                  <b>{r.ticker}</b>
                  <span>{r.alert_filing_date}</span>
                  <span>{r.conviction_score}</span>
                </button>
              ))}
            </div>
          </section>
        </div>
      </Feedback>
      {id > 0 && (
        <section className="panel">
          <Feedback loading={detail.isPending} error={detail.error}>
            {a && (
              <>
                <h2>
                  {a.ticker} · Filing detail{" "}
                  <button
                    onClick={() => {
                      set({});
                    }}
                  >
                    Close
                  </button>
                </h2>
                <p>
                  {usd(a.total_value_usd)} · {a.n_insiders} insiders ·{" "}
                  {a.status}
                </p>
                <dl>
                  {Object.entries(a.score_breakdown).map(([k, v]) => (
                    <div key={k}>
                      <dt>{k}</dt>
                      <dd>
                        {typeof v === "number" ? v.toFixed(3) : String(v)}
                      </dd>
                    </div>
                  ))}
                </dl>
                <table>
                  <thead>
                    <tr>
                      <th>Insider ID</th>
                      <th>Trade date</th>
                      <th>Value</th>
                      <th>Filing</th>
                    </tr>
                  </thead>
                  <tbody>
                    {a.members.map((t) => (
                      <tr key={t.id}>
                        <td>{t.insider_id}</td>
                        <td>{t.transaction_date}</td>
                        <td>{usd(t.value_usd ?? 0)}</td>
                        <td>
                          {t.raw_xml_url.startsWith("https://") ? (
                            <a href={t.raw_xml_url}>SEC filing ↗</a>
                          ) : (
                            t.accession_number
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="actions">
                  <button
                    disabled={action.isPending}
                    onClick={() => {
                      action.mutate("acknowledged");
                    }}
                  >
                    Acknowledge
                  </button>
                  <button
                    disabled={action.isPending}
                    onClick={() => {
                      action.mutate("dismissed");
                    }}
                  >
                    Dismiss
                  </button>
                  <a
                    href={
                      "/workbench/?ticker=" +
                      encodeURIComponent(a.ticker) +
                      "&alert_id=" +
                      String(a.id)
                    }
                  >
                    Inspect Form 4 ↗
                  </a>
                </div>
                {action.error && <p role="alert">{action.error.message}</p>}
              </>
            )}
          </Feedback>
        </section>
      )}
    </>
  );
}
