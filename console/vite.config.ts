import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3010,
    proxy: {
      "/api/atlas": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
      },
      "/api/probe": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
      },
      "/api/lens": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
      },
      "/api/chat": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
      },
      "/svc/atlas": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
      },
      "/svc/probe": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
      },
      "/svc/lens": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
      },
    },
  },
});
