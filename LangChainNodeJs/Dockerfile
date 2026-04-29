FROM node:20-slim

ENV NODE_ENV=production \
    LOOP_FOREVER=1 \
    LOOP_INTERVAL_SECONDS=60

WORKDIR /app

COPY package.json /app/package.json
RUN npm install --omit=dev --no-audit --no-fund

COPY main.js /app/main.js
COPY instrumentation.js /app/instrumentation.js

CMD ["node", "--import", "./instrumentation.js", "main.js"]
