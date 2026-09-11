// 新建项目页面 —— 直接渲染 NewProjectWizard。点侧栏「新建项目」进这里,
// 不再跳到监控项目列表。
//
// 进路由时给 <body> 加 ``windx-new-project`` 类,AppLayout.css 据此把
// ``.app-content`` 的 padding 归零、去掉背景;这样 wizard 的步骤条/底部
// 会和侧栏右侧完全贴边,不再有「卡片套卡片」的多余余白。
//
// 提交成功后,wizard 自己弹提示并清空表单回到 step 1(用户继续在原页
// 编辑下一份,不去待审核列表)—— 因此这里只挂 useEffect 管 body class,
// 不再传 onSubmitted。

import { useEffect } from "react";
import NewProjectWizard from "./NewProjectWizard";
import "./NewProject.css";

const BODY_CLASS = "windx-new-project";

export default function NewProjectPage() {
  useEffect(() => {
    document.body.classList.add(BODY_CLASS);
    return () => {
      document.body.classList.remove(BODY_CLASS);
    };
  }, []);
  return (
    <div className="new-project-page">
      <NewProjectWizard />
    </div>
  );
}