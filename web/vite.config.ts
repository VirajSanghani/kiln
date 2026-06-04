import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In docker the proxy target is the api service; locally it defaults to localhost.
// Same-origin /api proxy means the browser never needs CORS in the normal flow.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
