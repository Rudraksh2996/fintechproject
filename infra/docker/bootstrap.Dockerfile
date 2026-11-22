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
COPY alembic.ini ./
COPY edgar_pipeline/migrations ./edgar_pipeline/migrations
COPY infra/scripts/bootstrap.py infra/scripts/verify_model.py infra/neo4j/constraints.cypher infra/verification/phase3/metrics-lite.json ./
RUN mkdir -p /artifacts && chown 65532:65532 /artifacts
USER 65532:65532
CMD ["python","/platform/bootstrap.py"]
