FROM ghcr.io/astral-sh/uv:0.9.11 AS uv
FROM python:3.12.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_NO_CACHE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 VIRTUAL_ENV=/opt/ml PATH=/opt/ml/bin:$PATH
WORKDIR /platform
RUN uv venv /opt/ml && uv pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
RUN uv pip install torch-geometric==2.6.1 scipy==1.15.3 && uv pip install --no-deps --no-index --find-links https://data.pyg.org/whl/torch-2.8.0+cpu.html torch-scatter==2.1.2+pt28cpu torch-sparse==0.6.18+pt28cpu
COPY ml_pipeline ./ml_pipeline
RUN uv pip install ./ml_pipeline && mkdir /artifacts && chown 65532:65532 /artifacts
COPY infra/scripts/verify_model.py /platform/verify_model.py
USER 65532:65532
CMD ["python", "-m", "ml_pipeline.gnn.train", "/artifacts"]
