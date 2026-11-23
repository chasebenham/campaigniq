import { fileURLToPath } from "node:url"
import { resolve } from "node:path"
import { defineConfig } from "vitest/config"
import { loadEnv } from "vite"
import react from "@vitejs/plugin-react"
import tailwind from "@tailwindcss/vite"

const directory = fileURLToPath(new URL(".", import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, resolve(directory, ".."), "")
  const proxy = { "/api": env.API_PROXY_TARGET || "http://127.0.0.1:8000" }
  return {
    plugins: [react(), tailwind()],
    resolve: { alias: { "@": resolve(directory, "src") } },
    server: { proxy },
    preview: { proxy },
    test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"] },
  }
})
