FROM ghcr.io/astral-sh/uv:0.9.11 AS uv
FROM python:3.12.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_NO_CACHE=1 PYTHONUNBUFFERED=1
WORKDIR /platform
COPY pyproject.toml uv.lock ./
COPY ml_pipeline/pyproject.toml ml_pipeline/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml
COPY edgar_pipeline edgar_pipeline
COPY streamlit_workbench streamlit_workbench
RUN uv sync --frozen --no-dev --package quant-workbench --no-editable
WORKDIR /platform/streamlit_workbench
USER 65532:65532
CMD ["/platform/.venv/bin/streamlit","run","app.py","--server.address=0.0.0.0","--server.baseUrlPath=workbench"]
