FROM ghcr.io/astral-sh/uv:0.9.11 AS uv
FROM python:3.12.12-slim-bookworm
ENV UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1 VIRTUAL_ENV=/opt/research PATH=/opt/research/bin:$PATH
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=bind,source=.,target=/src,ro cd /src && \
    uv venv --python /usr/local/bin/python3.12 /opt/research && \
    uv export --python /usr/local/bin/python3.12 --frozen --package quant-workbench --no-dev --no-emit-workspace --no-hashes -o /tmp/deps && \
    uv pip install -r /tmp/deps && uv pip install --no-deps ./edgar_pipeline ./streamlit_workbench && rm /tmp/deps
WORKDIR /workbench
COPY streamlit_workbench/app.py .
COPY streamlit_workbench/pages ./pages
COPY streamlit_workbench/.streamlit ./.streamlit
COPY infra/scripts/check_workbench_image.py /tmp/check_workbench_image.py
RUN python /tmp/check_workbench_image.py
USER 65532:65532
CMD ["streamlit","run","app.py","--server.address=0.0.0.0","--server.baseUrlPath=workbench"]
