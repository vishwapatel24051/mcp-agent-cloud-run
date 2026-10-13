# ---- Build stage: install Python dependencies into an isolated virtualenv ----
FROM python:3.13-slim AS build
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Runtime stage ----
FROM python:3.13-slim
WORKDIR /app

# Node.js runs the filesystem and Tavily MCP servers (stdio subprocesses) and readabilipy's HTML
# extraction for the fetch server. Debian's packaged Node 20 is too old for readabilipy's
# dependencies (undici fails to load), so copy a current Node from the official image.
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Install the Node MCP servers at build time so cold starts never download packages.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

# A venv under /opt (not /root/.local) stays readable after we drop root.
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    WORKSPACE_DIR=/app/workspace

# mcp-server-fetch converts HTML with readabilipy, which runs `npm install` inside site-packages
# on first use. The non-root user cannot write there, so do it now, as root, at build time.
RUN cd /opt/venv/lib/python3.13/site-packages/readabilipy/javascript && npm install --omit=dev && npm cache clean --force

COPY main.py agent.py mcp_client.py utils_server.py mcp_config.json ./
RUN useradd -m appuser && mkdir -p /app/workspace && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
CMD ["python", "main.py"]
