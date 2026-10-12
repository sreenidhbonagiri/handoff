import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  define: {
    "import.meta.env.VITE_PUBLIC_SHOWCASE": JSON.stringify("true"),
  },
  base: "/handoff/",
  build: {
    outDir: "dist-showcase",
    emptyOutDir: true,
    rollupOptions: {
      input: "showcase.html",
    },
  },
});
