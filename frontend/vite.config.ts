import { readFileSync } from "node:fs";
import { join } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const API = "http://127.0.0.1:5680";

// In dev (npm run dev), inject the service's API token the same way the service does in
// production. Start the service with `python main.py serve --dev` so it accepts this origin.
function devToken(): Plugin {
  return {
    name: "studio-dev-token",
    apply: "serve",
    transformIndexHtml(html) {
      const file = join(process.env.LOCALAPPDATA ?? "", "AutomationEngine", "api.token");
      let token = "";
      try {
        token = readFileSync(file, "utf8").trim();
      } catch {
        console.warn(`[studio] no token at ${file}; start the service first`);
      }
      return html.replace("<!--studio-token-->", `<meta name="studio-token" content="${token}">`);
    },
  };
}

export default defineConfig({
  plugins: [react(), devToken()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: API, changeOrigin: true },
      "/ws": { target: API, changeOrigin: true, ws: true },
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
});
