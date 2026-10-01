# approximately — zero dependencies, so the image is just Python.
# The MCP server speaks stdio, so run it with -i (keep stdin open):
#   docker build -t approximately .
#   docker run -i --rm -v "$PWD/agents:/agents" approximately \
#     mcp --store /agents/store
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# traces default to a volume-friendly path when --store is omitted
ENV APPROXIMATELY_HOME=/agents/store
RUN mkdir -p /agents/store

ENTRYPOINT ["approximately"]
CMD ["mcp"]
