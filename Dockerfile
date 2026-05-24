FROM python:3.10-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install -e ".[all]"

CMD ["ai-edge-monitor", "--help"]
