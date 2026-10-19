// @ts-nocheck  vite config 引用 node 标准库,工程未装 @types/node
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";

// 把 windx_ai_brand_monitor.html(营销落地页)做成 / 的入口:
//   - 生产(vite build):closeBundle 把源文件原样拷到 dist/,后端静态
//     fallback 已在 _serve_frontend 优先指向它
//   - 开发(vite dev):configureServer middleware 让 / 直接 serve 它,
//     其他路径由 Vite 自己走 React SPA
// 落地页本身没有 <script type="module"> / import,Vite 不需要对它做
// 任何 transform,只要"原样输出 / 原样回流"。
export default defineConfig({
  plugins: [
    {
      name: "serve-landing-on-root",
      apply: "build",
      closeBundle() {
        const src = path.resolve("./windx_ai_brand_monitor.html");
        const dest = path.resolve("./dist/windx_ai_brand_monitor.html");
        if (!fs.existsSync(src)) return;
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.copyFileSync(src, dest);
      },
    },
    {
      name: "serve-landing-on-root-dev",
      apply: "serve",
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url !== "/" && req.url !== "") return next();
          const src = path.resolve("./windx_ai_brand_monitor.html");
          if (!fs.existsSync(src)) return next();
          try {
            const content = fs.readFileSync(src, "utf-8");
            res.setHeader("Content-Type", "text/html; charset=utf-8");
            res.end(content);
            return;
          } catch (err) {
            return next(err);
          }
        });
      },
    },
    react(),
  ],
  server: {
    host: "0.0.0.0",  // 让外部(SSH 之外的浏览器)能访问 dev server
    port: 5173,
    proxy: {
      // 127.0.0.1 而非 localhost:某些发行版 /etc/hosts 上 localhost
      // 解析到 ::1(IPv6 loopback),后端 uvicorn 只 bind IPv4 就拒 700
      "/api": "http://127.0.0.1:18083",
      "/static": "http://127.0.0.1:18083",
    },
  },
});
