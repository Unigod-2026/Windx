// PM2 ecosystem config for windx.
// 关键点:
//   - interpreter: "none" — uvicorn 是可执行 binary,不要 PM2 套 node 解释器
//   - exec_mode: "fork" — Python 没 cluster 模式,workers 走 uvicorn 自身的 --workers N
//   - cwd/script 必须是绝对路径 —— PM2 daemon 解析这两个字段时用的是
//     daemon 进程的 cwd(不是 deploy.sh 调用 pm2 时的 cwd),写相对路径
//     会按 daemon 的 cwd 解析,得到 /home/deploy/... 这种错位路径
//     (实测就是这样挂的)。
//   - 此文件被 deploy.sh 读,deploy.sh 已知 REPO_ROOT 绝对路径,通过
//     环境变量 PM2_CONFIG_CWD 注入,这里接收。
const repoRoot = process.env.PM2_CONFIG_CWD;
if (!repoRoot) {
  throw new Error(
    "PM2_CONFIG_CWD env var required — deploy.sh sets it to the repo root"
  );
}

module.exports = {
  apps: [
    {
      name: "windx-backend",
      script: `${repoRoot}/deploy/start-backend.sh`,
      interpreter: "none",
      exec_mode: "fork",
      cwd: `${repoRoot}/backend`,
      // Python 自己管 worker,这里只起 1 个 PM2 监测进程就行
      instances: 1,
      // 资源 / 重启策略
      max_memory_restart: "1G",
      restart_delay: 5000,
      max_restarts: 10,
    },
  ],
};