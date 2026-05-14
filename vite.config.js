import { defineConfig } from "vite";

export default defineConfig({
  base: process.env.VITE_BASE || "/",
  server: {
    host: "0.0.0.0",
    allowedHosts: true,
    port: 8283,
    // strictPort: true,
    // open: true // Open browser on server start
    // cors: true,
    proxy: {
      // Proxy requests starting with '/api' backend URL
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});
