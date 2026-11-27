import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In Docker, /api is proxied to the backend container. Locally it falls back to localhost:8000.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": process.env.API_TARGET || "http://localhost:8000" } },
});
