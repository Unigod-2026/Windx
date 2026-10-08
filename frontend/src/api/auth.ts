/** ``/api/auth`` 端点的 thin wrapper —— ``AuthProvider`` 已经包了 ``/me`` GET,
 *  这里只放写路径(patchMe / changePassword),跟 GET 拆开避免在 AuthProvider
 *  的 mount-time 探针里误打到写路径。 */
import client from "./client";
import type { User } from "../auth/AuthProvider";

/** PATCH /api/auth/me —— 局部更新,只传需要改的字段。 */
export interface ProfilePatch {
  email?: string | null;
  phone?: string | null;
  notification_prefs?: {
    mention: boolean;
    drop: boolean;
    report: boolean;
    system: boolean;
  } | null;
}

export function patchMe(payload: ProfilePatch): Promise<User> {
  return client.patch<User>("/auth/me", payload).then((r) => r.data);
}

/** POST /api/auth/change-password —— 改密。后端会在旧密码错时 401、
 *  新密码不合规(≥8 位 + 字母 + 数字)时 422,前端直接读 detail 提示。 */
export function changePassword(payload: {
  old_password: string;
  new_password: string;
}): Promise<{ ok: true }> {
  return client
    .post<{ ok: true }>("/auth/change-password", payload)
    .then((r) => r.data);
}
