// PM2 ecosystem config for windx.
// 路径都是相对 deploy/ 的相对路径,git clone 到任何目录都 work。
// deploy.sh 优先用这份配置 + start-backend.sh(声明式 + .env 加载),
// 若两份文件都不存在,fall back 到「假设 windx-backend 已经在 PM2 里
// 注册」的 reloadOrRestart(命令式,适合手动 pm2 start 起来的进程)。
//
// 关键点:
//   - interpreter: "none" — uvicorn 是可执行 binary,不要 PM2 套 node 解释器
//   - exec_mode: "fork" — Python 没 cluster 模式,workers 走 uvicorn 自身的 --workers N
//   - cwd: ../backend — 让 start-backend.sh 用相对路径找 .env

module.exports = {
  apps: [
    {
      name: "windx-backend",
      script: "../deploy/start-backend.sh",
      interpreter: "none",
      exec_mode: "fork",
      cwd: "../backend",
      // Python 自己管 worker,这里只起 1 个 PM2 监测进程就行
      instances: 1,
      // 资源 / 重启策略
      max_memory_restart: "1G",
      restart_delay: 5000,
      max_restarts: 10,
    },
  ],
};