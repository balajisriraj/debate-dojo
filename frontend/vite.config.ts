import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs on :8060; in production nginx serves both from one origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5185,
    proxy: { "/api": { target: process.env.DEBATEDOJO_API ?? "http://127.0.0.1:8060", changeOrigin: true } },
  },
  test: { environment: "node" },
});
