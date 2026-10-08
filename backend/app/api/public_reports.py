"""Public report endpoints — no authentication required.

These endpoints are reached via the share URL embedded in the report
preview, intended to be sent over IM (WeChat etc.) to anyone. The
caller proves they're allowed to see the report by presenting a valid
``share_token`` — a 256-bit URL-safe random value generated at report
creation (see ``_generate_unique_share_token``).

Authentication-free by design:
- The /api/public/* path prefix is **not** behind ``get_current_user``;
  no JWT required.
- 只在 ``is_published=True`` 时返回内容:未发布的周报需要登录后通过
  auth-gated 路径(/api/reports/{id}) 查看 / 编辑。
- 服务预渲染的静态 HTML —— public 端不做 snapshot 重算,避免每次访问
  都重跑全套 mention / 引用聚合(几秒级开销)。
  HTML 在 ``POST /api/reports/{id}/publish`` 时由后端
  ``render_html`` + 写盘生成;取消发布会删除磁盘文件。

Why a separate router (not a path on the existing ``reports`` router):
the existing router uses ``Depends(get_current_user)`` per-endpoint;
mounting a public endpoint on it would either require an
authentication-skipping flag (easy to misuse) or split the route table
with non-obvious gating. A separate router keeps the contract
self-evident — *all* endpoints under ``/api/public/*`` are open, *all*
under ``/api/reports/*`` require auth.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.report import Report as ReportRow

router = APIRouter(tags=["public-reports"])


# backend/app/api/public_reports.py → backend/...
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


@router.get(
    "/api/public/reports/{share_token}",
    response_class=HTMLResponse,
    responses={404: {"description": "token unknown or report unpublished"}},
)
def get_public_report_html(
    share_token: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Public preview endpoint — anyone with the token can read。

    行为契约:
      - token 找不到或 ``is_published=False`` → 404(两个统一 404,避免泄漏
        「token 存在但未发布」的中间态)。
      - token 命中 + 已发布 → 返回预渲染的 HTML 文本(``text/html``)。
      - HTML 文件缺失(发布失败 / 文件被人删)→ 503,提示重新发布。
        这两类都不应出现在 happy path —— publish 路径会保证文件就位。
    """
    row = db.query(ReportRow).filter(ReportRow.share_token == share_token).first()
    if row is None or not row.is_published:
        raise HTTPException(status_code=404, detail="report not found")

    if not row.file_path:
        # 边缘情况:row 创建过 + 走过 publish 路径但 file_path 为空
        # ——publish 路径应该已经写盘了,这里兜底 503 而不是给个空页面
        raise HTTPException(status_code=503, detail="html not generated")
    html_path = _BACKEND_ROOT / row.file_path
    if not html_path.exists():
        raise HTTPException(status_code=503, detail="html file missing")

    # ``no-store`` 强制浏览器每次重新拉,不让任何中间层(浏览器 disk
    # cache / CDN / 代理)缓存住上一版的周报 HTML —— publish 会覆盖
    # 同一文件路径,运营期望「点完发布,链接打开就是新版」。
    return HTMLResponse(
        content=html_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )
