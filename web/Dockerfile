# KILN web — dev image (Phase 0). Runs the vite dev server with /api proxied to the
# api service. A production multi-stage (build + static serve) image is a Phase 6 seam.
FROM node:22-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
