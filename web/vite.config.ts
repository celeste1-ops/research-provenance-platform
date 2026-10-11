import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

// In `make dev` the backend writes its per-launch session token to a file in the
// data directory; this plugin injects it into the page (never into a URL), the
// same way the backend does for the built UI in `make run`.
function devSessionToken() {
  return {
    name: "rprov-dev-session-token",
    apply: "serve" as const, // the built page keeps the placeholder; the backend fills it in
    transformIndexHtml(html: string) {
      const home = process.env.RPROV_HOME ?? join(homedir(), ".rprov");
      const file = join(home, "dev-session-token");
      const token = existsSync(file) ? readFileSync(file, "utf8").trim() : "";
      return html.replace("__RPROV_SESSION_TOKEN__", token);
    },
  };
}

const backend = `http://127.0.0.1:${process.env.RPROV_PORT ?? "8765"}`;

export default defineConfig({
  plugins: [react(), devSessionToken()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: backend, changeOrigin: false } },
  },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 2000 },
});
