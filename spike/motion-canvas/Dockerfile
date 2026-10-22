FROM node:24.22.1-bookworm-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
RUN npm install --no-save playwright@1.64.0
RUN npx playwright install --with-deps chromium
COPY . .
CMD ["node", "driver.mjs"]
