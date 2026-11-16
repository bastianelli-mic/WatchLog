import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In sviluppo `npm run dev` gira su un'altra porta: le chiamate /api vanno all'API avviata con `watchlog api`.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
