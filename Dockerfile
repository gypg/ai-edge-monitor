FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for psutil and matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY docs/dashboard.html ./dashboard.html
COPY examples ./examples

RUN python -m pip install --upgrade pip \
    && python -m pip install -e ".[all]"

# Web dashboard port
EXPOSE 17429

# Default: start web dashboard on all interfaces
CMD ["ai-edge-monitor", "dashboard", "--host", "0.0.0.0", "--port", "17429", "--duration", "86400"]
