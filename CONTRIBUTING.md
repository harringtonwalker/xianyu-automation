# Contributing

感谢你改进 Xianyu Automation。提交代码即表示你有权提供该贡献，并同意按 Apache-2.0 许可证发布。

## 开发环境

```bash
git clone https://github.com/harringtonwalker/xianyu-automation.git
cd xianyu-automation
./scripts/setup.command
./scripts/verify.command
```

Node.js 20+ 仅用于扩展测试；运行本地服务需要 Python 3.11+。

## 提交要求

1. 从最新默认分支创建主题分支；
2. 改动保持有界，新增行为必须包含相应测试；
3. 运行 `./scripts/verify.command`；
4. 检查 `git diff --cached`，确认没有 `data/`、`backups/`、数据库、日志、图片素材、令牌、Cookie、API Key、账号 ID 或客户资料；
5. Pull Request 说明问题、实现、失败路径和验证结果。

## 可接受的贡献

- 当前发布页语义契约的兼容修复；
- 内容事实约束、水印排版、去重、租约、回执或恢复能力；
- 单元测试、集成测试、文档和可访问性改进；
- 更严格的最小权限、隐私保护和失败关闭机制。

## 不接受的贡献

- Cookie 导出或注入；
- `debugger`、全站浏览权限或无关的宽权限；
- stealth、指纹伪装、验证码绕过或反检测；
- 竞争对手商品搬运、去水印或未授权抓取；
- 取消人工内容复核、批次审批或风险熔断；
- 回执不确定时自动重复点击发布；
- 宣称规避平台规则、保证账号安全或保证永久兼容。

## 页面契约变更

页面结构发生变化时，请提供脱敏的字段描述、复现步骤和测试。不要提交登录态、Cookie、用户 ID、真实商品、截图中的个人信息或内部接口凭据。契约更新必须保持“发现漂移即停止”的默认行为。
