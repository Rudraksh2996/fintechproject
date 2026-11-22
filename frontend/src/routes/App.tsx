import { lazy, Suspense } from "react";
import {
  Activity,
  ArrowUpRight,
  Boxes,
  FlaskConical,
  LayoutDashboard,
  Network,
  Radar,
} from "lucide-react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { useHealth, useInfo, useRadar, useRings } from "../api/client";
import { usd } from "../lib/display";
import { useLive, useLiveChannel } from "../ws/useLiveChannel";
import { Feedback } from "../components/Feedback";
const RadarPage = lazy(() => import("./Radar"));
const MulePage = lazy(() => import("./Mule"));

function Home() {
  const alerts = useRadar(),
    rings = useRings(),
    events = useLive((s) => s.events);
  const sorted = [...(alerts.data ?? [])].sort((a, b) =>
    b.alert_filing_date.localeCompare(a.alert_filing_date),
  );
  return (
    <>
      <header>
        <h1>Command center</h1>
      </header>
      <div className="kpis">
        {[
          ["Cluster alerts", alerts.data?.length],
          [
            "Reported purchases",
            alerts.data
              ? usd(
                  alerts.data.reduce(
                    (v, a) => v + Number(a.total_value_usd),
                    0,
                  ),
                )
              : undefined,
          ],
          ["Candidate rings", rings.data?.length],
          ["Highest ring risk", rings.data?.[0]?.risk.toFixed(1)],
        ].map(([label, value]) => (
          <section key={label}>
            <small>{label}</small>
            <strong>{value ?? "—"}</strong>
          </section>
        ))}
      </div>
      <div className="columns">
        <section className="panel">
          <h2>
            <Radar /> Insider clusters{" "}
            <Link to="/radar" aria-label="Open radar">
              <ArrowUpRight />
            </Link>
          </h2>
          <Feedback
            loading={alerts.isPending}
            error={alerts.error}
            empty={!sorted.length}
          >
            <table>
              <thead>
                <tr>
                  <th>Issuer</th>
                  <th>Filed</th>
                  <th>Conviction</th>
                </tr>
              </thead>
              <tbody>
                {sorted.slice(0, 8).map((a) => (
                  <tr key={a.id}>
                    <td>
                      <Link to={"/radar?id=" + String(a.id)}>{a.ticker}</Link>
                    </td>
                    <td>{a.alert_filing_date}</td>
                    <td>{a.conviction_score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Feedback>
        </section>
        <section className="panel">
          <h2>
            <Network /> Highest-risk rings{" "}
            <Link to="/mule" aria-label="Open explorer">
              <ArrowUpRight />
            </Link>
          </h2>
          <Feedback
            loading={rings.isPending}
            error={rings.error}
            empty={!rings.data?.length}
          >
            {rings.data?.slice(0, 6).map((r) => (
              <Link
                className="riskrow"
                key={r.community}
                to={"/mule?ring=" + String(r.community)}
              >
                <span>Ring {r.community}</span>
                <meter min="0" max="100" value={r.risk} />
                <b>{r.risk.toFixed(1)}</b>
              </Link>
            ))}
          </Feedback>
        </section>
      </div>
      <section className="panel">
        <h2>
          <Activity /> Live events
        </h2>
        {events.length === 0 ? (
          <p className="notice">
            Listening for new alerts and score crossings.
          </p>
        ) : (
          events.slice(0, 20).map((e, i) => (
            <div className="event" key={String(e.time) + "-" + String(i)}>
              <time>{new Date(e.time).toLocaleTimeString()}</time>
              <span>{e.type.replaceAll("_", " ")}</span>
              <Link
                to={
                  e.type === "cluster_alert"
                    ? "/radar?id=" + String(e.id)
                    : e.type === "ring_detected"
                      ? "/mule?ring=" + String(e.id)
                      : "/mule?account=" + String(e.id)
                }
              >
                {e.label}
              </Link>
              <b>{e.value.toFixed(1)}</b>
            </div>
          ))
        )}
      </section>
    </>
  );
}
function Workbench() {
  return (
    <>
      <header>
        <h1>Quant workbench</h1>
        <a href="/workbench/" target="_blank" rel="noreferrer">
          Open in new tab ↗
        </a>
      </header>
      <iframe title="Quant Workbench" src="/workbench/?embed=true" />
    </>
  );
}
export function App() {
  useLiveChannel("alerts");
  useLiveChannel("mule");
  const status = useLive((s) => s.status),
    info = useInfo(),
    health = useHealth();
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <Boxes /> Meridian
        </div>
        <nav>
          {[
            { to: "/", label: "Command center", Icon: LayoutDashboard },
            { to: "/radar", label: "Insider cluster radar", Icon: Radar },
            { to: "/mule", label: "Mule explorer", Icon: Network },
            { to: "/research", label: "Quant workbench", Icon: FlaskConical },
          ].map(({ to, label, Icon }) => (
            <NavLink end key={to} to={to}>
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="service">
          <i className={health.data?.status === "ok" ? "on" : ""} />
          Gateway {health.data?.status ?? "unavailable"}
        </div>
      </aside>
      <main>
        <div className="topbar">
          <span className="provenance">
            {info.data?.demo_mode
              ? "Synthetic demo data"
              : info.data
                ? "Live data"
                : "Connecting"}
          </span>
          <div>
            <span>
              <i className={status.alerts === "live" ? "on" : ""} />
              Alerts {status.alerts}
            </span>
            <span>
              <i className={status.mule === "live" ? "on" : ""} />
              Mule {status.mule}
            </span>
            <span>
              {info.data?.model_architecture} {info.data?.model_version}
            </span>
          </div>
        </div>
        <div className="content">
          <Suspense fallback={<p>Loading view…</p>}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/radar" element={<RadarPage />} />
              <Route path="/mule" element={<MulePage />} />
              <Route path="/research" element={<Workbench />} />
              <Route
                path="*"
                element={
                  <p>
                    Page unavailable. <Link to="/">Command center</Link>
                  </p>
                }
              />
            </Routes>
          </Suspense>
        </div>
      </main>
    </div>
  );
}
