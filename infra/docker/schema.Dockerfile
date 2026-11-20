FROM ghcr.io/astral-sh/uv:0.9.11 AS uv
FROM python:3.12.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /platform
COPY pyproject.toml uv.lock alembic.ini ./
COPY edgar_pipeline ./edgar_pipeline
COPY ml_pipeline ./ml_pipeline
COPY backend ./backend
COPY streamlit_workbench ./streamlit_workbench
COPY infra/scripts ./infra/scripts
RUN uv sync --frozen --no-dev --all-packages
USER 65532:65532
CMD ["/platform/.venv/bin/alembic", "upgrade", "head"]
