import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 서버에서 /api 를 백엔드(uvicorn, 8000)로 넘긴다.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
