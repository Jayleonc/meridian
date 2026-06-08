# Meridian Development Log

## 2026-06-08
* **Feature Removal**: 完全移除了之前引入的演示模式（Demo Mode）和密码访问门禁。
    * 删除了 `LoginPage.tsx` 及所有的前端身份验证、拦截和页面重定向逻辑。
    * 清除了后端 (Nexus) 的 `_demo_blocks_request` 路由限制和 `DemoSettings` 读取。
    * 移除了演示专用的受限数据面板和禁用组件。
    * 项目重新回归对所有开发人员和环境完全开放的状态（移除提交 `47dda6f`）。
