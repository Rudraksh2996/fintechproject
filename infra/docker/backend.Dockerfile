FROM scratch AS sources
COPY pyproject.toml uv.lock /
COPY backend/pyproject.toml /backend/pyproject.toml
COPY streamlit_workbench/pyproject.toml /streamlit_workbench/pyproject.toml
COPY edgar_pipeline /edgar_pipeline
COPY ml_pipeline /ml_pipeline
FROM ml_base AS runtime
RUN --mount=type=bind,from=sources,target=/src,ro cd /src && \
    uv export --python /opt/ml/bin/python --frozen --package fintech-gateway --no-dev --no-emit-workspace --no-hashes -o /tmp/deps && \
    uv pip install -r /tmp/deps && uv pip install --no-deps ./edgar_pipeline ./ml_pipeline && rm /tmp/deps && uv pip check
FROM runtime
RUN --mount=type=bind,source=backend,target=/src/backend,ro uv pip install --no-sources --no-deps /src/backend && mkdir -p /cache && chown 65532:65532 /cache
USER 65532:65532
CMD ["uvicorn","app.main:create_app","--factory","--host","0.0.0.0","--port","8000"]
