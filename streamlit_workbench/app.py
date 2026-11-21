import streamlit as st
from quant_workbench.pages import render

render(
    "Form 4 Inspector"
    if "ticker" in st.query_params or "alert_id" in st.query_params
    else "Threshold Tuner"
)
