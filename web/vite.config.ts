import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [react()],
    base: env.VITE_BASE_PATH || "/",
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/v1": "http://127.0.0.1:8000",
        "/health": "http://127.0.0.1:8000",
      },
    },
  };
});
