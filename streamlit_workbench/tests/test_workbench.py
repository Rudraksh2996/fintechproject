"""Render and exercise the analyst pages with production SQL and HTTP paths."""

import os
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "page,widget",
    [
        ("1_Threshold_Tuner.py", "slider"),
        ("2_Backtester.py", "plotly_chart"),
        ("3_Form_4_Inspector.py", "code"),
        ("4_Exports.py", "download_button"),
    ],
)
def test_page(page: str, widget: str) -> None:
    at = AppTest.from_file(ROOT / "pages" / page, default_timeout=30).run()
    assert not at.exception and not at.error and at.get(widget)


def test_inspector_link_and_config_activation() -> None:
    url = os.environ["GATEWAY_URL"] + "/api/v1/insider"
    with httpx.Client(base_url=url) as api:
        alert = api.get("alerts?limit=1").json()["items"][0]
        inspector = AppTest.from_file(ROOT / "app.py", default_timeout=30)
        inspector.query_params.update(ticker=alert["ticker"], alert_id=str(alert["id"]))
        inspector.run()
        assert (
            not inspector.error
            and inspector.code
            and inspector.text_input[0].value == alert["ticker"]
        )
        active = next(c for c in api.get("configs").json() if c["is_active"])
        tuner = AppTest.from_file(ROOT / "pages/1_Threshold_Tuner.py", default_timeout=30).run()
        tuner.text_input[0].set_value("Workbench integration").run()
        tuner.button[0].click().run()
        assert not tuner.error and not tuner.exception
        try:
            tuner.button[1].click().run()
            new = next(c for c in api.get("configs").json() if c["is_active"])
            assert new["name"] == "Workbench integration" and new["id"] != active["id"]
        finally:
            api.post(f"configs/{active['id']}/activate").raise_for_status()
