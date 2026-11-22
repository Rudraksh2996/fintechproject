"""Analyst views. Database access uses the read-only role; mutations use the gateway."""

from collections.abc import Hashable, Mapping
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pandas as pd
import plotly.express as px  # type: ignore[import-untyped]
import streamlit as st
from edgar_pipeline.backtest import ForwardReturn, summarize
from edgar_pipeline.conviction import Config
from edgar_pipeline.form4_parser import parse_form4
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from quant_workbench.research import Environment, clusters, frame, returns


@st.cache_resource
def resources() -> tuple[Environment, Engine]:
    env = Environment()
    return env, env.engine()


def config_from(row: Mapping[Hashable, Any] | Mapping[str, Any]) -> Config:
    return Config(**{k: row[k] for k in Config.__dataclass_fields__})


def post(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    env, _ = resources()
    response = httpx.post(env.gateway_url + "/api/v1/insider/" + path, json=payload, timeout=15)
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def tuner() -> None:
    env, engine = resources()
    rows = frame(engine, "SELECT * FROM detection_configs ORDER BY id DESC").to_dict("records")
    active = next(row for row in rows if row["is_active"])
    values = {}
    fields = {
        "window_days": (1, 90),
        "min_insiders": (2, 20),
        "cap_insiders": (2, 30),
        "min_insider_value_usd": (1.0, 500000.0),
        "min_cluster_value_usd": (1.0, 5000000.0),
        "holdings_cap": (0.01, 5.0),
        "value_cap_multiple": (1.01, 500.0),
        "new_position_pct": (0.01, 5.0),
        **{k: (0.0, 1.0) for k in ("w_b", "w_c", "w_v", "w_h")},
    }
    for key, (lo, hi) in fields.items():
        v = active[key]
        value = int(v) if isinstance(lo, int) else float(v)
        values[key] = st.slider(
            key.replace("_", " "), min(lo, value), max(hi, value), value, key=key
        )
    for key in ("include_ten_percent_owners", "exclude_10b5_1"):
        values[key] = st.checkbox(key.replace("_", " "), value=active[key])
    cfg_values = {k: (Decimal(str(v)) if isinstance(v, float) else v) for k, v in values.items()}
    try:
        config = config_from(cfg_values)
    except ValueError as exc:
        st.warning(str(exc))
        return
    proposed, _ = clusters(engine, env.demo_mode, config, Decimal(str(values["new_position_pct"])))
    existing, _ = clusters(engine, env.demo_mode, config_from(active), active["new_position_pct"])
    old = {(c.company, c.start) for c in existing}
    new = {(c.company, c.start) for c in proposed}
    st.metric("Qualifying clusters", len(new), f"{len(new - old)} added · {len(old - new)} removed")
    changes = [
        {"parameter": k, "active": str(active[k]), "proposed": str(v)}
        for k, v in cfg_values.items()
        if v != active[k]
    ]
    if changes:
        st.dataframe(changes)
    name = st.text_input("Configuration name")
    if st.button("Save as new config", disabled=not name.strip()):
        saved = post("configs", {"name": name.strip(), **values})
        st.session_state["saved_config"] = saved["id"]
        st.rerun()
    ids = [r["id"] for r in rows]
    chosen = st.selectbox(
        "Saved configuration",
        ids,
        index=ids.index(st.session_state.get("saved_config", active["id"])),
        format_func=lambda i: next(f"{r['name']} (#{i})" for r in rows if r["id"] == i),
    )
    if st.button("Activate", disabled=chosen == active["id"]):
        post(f"configs/{chosen}/activate")
        st.success(f"Activated configuration {chosen}")
    if st.button("Run detection"):
        st.info(f"Submitted job {post('detect')['id']}")


def backtest_controls() -> list[ForwardReturn]:
    env, engine = resources()
    rows = frame(engine, "SELECT * FROM detection_configs ORDER BY is_active DESC,id DESC").to_dict(
        "records"
    )
    chosen = st.selectbox(
        "Detection configuration",
        range(len(rows)),
        format_func=lambda i: f"{rows[i]['name']} (#{rows[i]['id']})",
    )
    bounds = frame(
        engine,
        "SELECT min(filing_date) AS lo,max(filing_date) AS hi "
        "FROM form4_filings WHERE source=:source",
        source="synthetic" if env.demo_mode else "sec_edgar",
    ).iloc[0]
    if not bounds.lo:
        st.info("No filings in this data source.")
        return []
    start = st.date_input("First filing date", value=bounds.lo)
    end = st.date_input("Last filing date", value=bounds.hi)
    if not isinstance(start, date) or not isinstance(end, date) or start > end:
        st.warning("Select an ordered date range.")
        return []
    row = rows[chosen]
    return returns(engine, env.demo_mode, config_from(row), row["new_position_pct"], start, end)


def backtester() -> None:
    results = backtest_controls()
    if not results:
        st.info("No signals with matching security and benchmark closes.")
        return
    for n, s in summarize(results).items():
        with st.expander(f"{n} trading sessions", expanded=n == 20):
            st.table(
                [
                    {
                        "Hit rate": f"{s.hit_rate:.1%}",
                        "Mean excess": f"{s.mean_excess:.2%}",
                        "Median excess": f"{s.median_excess:.2%}",
                    }
                ]
            )
            st.plotly_chart(
                px.histogram(x=list(map(float, s.distribution)), labels={"x": "Excess return"}),
                key=f"dist{n}",
            )
            st.plotly_chart(
                px.bar(
                    x=list(s.quintile_means),
                    y=list(map(float, s.quintile_means.values())),
                    labels={"x": "Conviction quintile", "y": "Mean excess return"},
                ),
                key=f"quint{n}",
            )


def inspector() -> None:
    env, engine = resources()
    ticker = st.query_params.get("ticker", "")
    alert = st.query_params.get("alert_id", "")
    if alert and not alert.isdecimal():
        st.warning("Invalid alert ID.")
        return
    query = st.text_input("Ticker, reporting owner or accession", value=ticker)
    filings = frame(
        engine,
        """SELECT f.accession_number,c.ticker,f.filing_date,f.raw_xml_url,f.raw_xml
    FROM form4_filings f JOIN companies c ON c.id=f.company_id WHERE f.source=:source
    AND (c.ticker ILIKE :q OR f.accession_number ILIKE :q OR EXISTS (
        SELECT 1 FROM unnest(xpath('//*[local-name()="rptOwnerName"]/text()',
         xmlparse(document f.raw_xml))) owner WHERE CAST(owner AS text) ILIKE :q))
    AND (:alert=0 OR EXISTS (SELECT 1 FROM cluster_alert_members m JOIN form4_transactions t
    ON m.transaction_id=t.id
    WHERE m.alert_id=:alert AND t.accession_number=f.accession_number))
    ORDER BY f.filing_date DESC, f.accession_number LIMIT 250""",
        source="synthetic" if env.demo_mode else "sec_edgar",
        q="%" + query + "%",
        alert=int(alert or 0),
    )
    if filings.empty:
        st.info("No matching filings.")
        return
    accession = st.selectbox("Filing accession", filings.accession_number.tolist())
    row = filings[filings.accession_number == accession].iloc[0]
    filing = parse_form4(row.raw_xml.encode())
    st.write(f"{row.ticker} · {filing.form} · filed {row.filing_date}")
    st.dataframe([asdict(owner) for owner in filing.owners])
    if filing.purchases:
        st.dataframe([asdict(purchase) for purchase in filing.purchases])
    else:
        st.info("This filing contains no qualifying open-market or private purchases (code P).")
    if not env.demo_mode:
        st.link_button("Open SEC filing", row.raw_xml_url)
    st.code(row.raw_xml, language="xml")


def exports() -> None:
    _, engine = resources()
    for label, sql in [
        ("Alerts", "SELECT * FROM cluster_alerts ORDER BY id"),
        (
            "Members",
            "SELECT m.alert_id,t.* FROM cluster_alert_members m JOIN form4_transactions t "
            "ON t.id=m.transaction_id ORDER BY m.alert_id,t.id",
        ),
    ]:
        data = frame(engine, sql)
        st.download_button(
            f"Download {label.lower()} ({len(data)})",
            data.to_csv(index=False),
            f"{label.lower()}.csv",
            "text/csv",
        )
    results = backtest_controls()
    data = pd.DataFrame(
        [
            {
                **asdict(r.signal),
                "entry": r.entry,
                "exit": r.exit,
                "sessions": r.sessions,
                "absolute": r.absolute,
                "excess": r.excess,
            }
            for r in results
        ]
    )
    st.download_button(
        f"Download backtest results ({len(data)})",
        data.to_csv(index=False),
        "backtest.csv",
        "text/csv",
    )


def render(title: str) -> None:
    st.set_page_config(page_title=title, layout="wide")
    env, _ = resources()
    st.sidebar.markdown("[Command center](/)")
    if env.demo_mode:
        st.caption("SYNTHETIC DEMO DATA")
    st.caption("Research tool — not investment advice.")
    st.title(title)
    try:
        {
            "Threshold Tuner": tuner,
            "Backtester": backtester,
            "Form 4 Inspector": inspector,
            "Exports": exports,
        }[title]()
    except (httpx.HTTPError, SQLAlchemyError) as exc:
        st.error(f"Research request failed ({type(exc).__name__}).")
