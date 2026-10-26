import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri memakai port tetap dan tidak boleh berganti diam-diam.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 5173, strictPort: true },
  build: { target: "es2022", sourcemap: false },
});
