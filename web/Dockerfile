# review.varuntx.us: the browser version of orchestra-review. Build from the repository root:
#   docker build -f web/Dockerfile -t orchestra-review-web .
# Pyodide is downloaded at build time and checked against a pinned hash, then served from this site,
# so visitors' browsers never load anything from a third party.
FROM python:3.12-alpine AS build
ARG PYODIDE=0.27.7
ARG PYODIDE_SHA256=9bc8f127db6c590b191b9aee754022cb41b1a36c7bac233776c11c5ecb541be8
WORKDIR /src
RUN apk add --no-cache curl bzip2 \
 && curl -fsSL -o /tmp/pyodide.tar.bz2 "https://github.com/pyodide/pyodide/releases/download/${PYODIDE}/pyodide-core-${PYODIDE}.tar.bz2" \
 && echo "${PYODIDE_SHA256}  /tmp/pyodide.tar.bz2" | sha256sum -c - \
 && mkdir -p /out /tmp/pyodide && tar -xjf /tmp/pyodide.tar.bz2 -C /tmp \
 && cp /tmp/pyodide/pyodide.js /tmp/pyodide/pyodide.asm.js /tmp/pyodide/pyodide.asm.wasm \
       /tmp/pyodide/python_stdlib.zip /tmp/pyodide/pyodide-lock.json /out/ \
 && mkdir /out/pyodide && mv /out/pyodide.js /out/pyodide.asm.js /out/pyodide.asm.wasm /out/python_stdlib.zip /out/pyodide-lock.json /out/pyodide/
COPY orchestra_review ./orchestra_review
COPY web ./web
RUN find orchestra_review -name '__pycache__' -prune -exec rm -rf {} + \
 && python -m zipfile -c /out/orchestra_review.zip orchestra_review \
 && python web/make_sample.py --out /out \
 && cp web/index.html web/app.js web/worker.js web/style.css web/favicon.svg /out/

FROM nginx:1.27-alpine
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /out /usr/share/nginx/html
# Count lines are appended here; mount a volume at this path to keep them across deploys.
RUN mkdir -p /var/log/counts
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO /dev/null http://127.0.0.1/healthz || exit 1
