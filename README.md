# OneAPI通用Token用量统计 AstrBot 插件
## 前置要求
服务器已部署 OneAPI 服务，获取管理员Token与日志接口地址。

## 配置修改说明
前往 AstrBot 插件可视化配置面板填写参数，无需修改源码：
1. ADMIN_TOKEN：OneAPI后台管理员密钥
2. ONE_API_URL：OneAPI日志接口地址
3. TARGET_TOKEN_NAME：需要统计的OneAPI令牌名称
4. FETCH_INTERVAL：日志拉取间隔，单位秒

## 指令列表
/token额度  查询选定令牌当日全局token消耗
/额度帮助  查看插件内置帮助文档
