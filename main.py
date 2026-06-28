import sqlite3
import aiohttp
from datetime import datetime, timezone
# 异步定时任务调度器，AstrBot官方推荐，不会阻塞机器人主线程
from apscheduler.schedulers.asyncio import AsyncIOScheduler
# AstrBot插件开发必备装饰器、上下文、消息事件类
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
# AstrBot内置日志打印工具，日志会输出到后台运行面板
from astrbot import logger
# AstrBot插件注册装饰器，统一修改名称、描述、版本号
@register(
    "astrbot_plugin_token_quota",
    "OneAPI通用Token用量统计",
    "定时同步OneAPI调用扣费日志，解决第三方插件中转调用时原生无法统计Token用量的问题，支持指令查询指定令牌当日总消耗额度",
    "0.0.2",
    "https://github.com/yingnannai/astrbot_plugin_token_quota"
)
class DrawQuotaPlugin(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.cfg = config
        self.ADMIN_TOKEN = self.cfg.get("ADMIN_TOKEN", "")
        self.ONE_API_URL = self.cfg.get("ONE_API_URL", "http://oneapi:3000/api/log/search")
        self.TARGET_TOKEN_NAME = self.cfg.get("TARGET_TOKEN_NAME", "业务统计令牌")
        self.FETCH_INTERVAL = int(self.cfg.get("FETCH_INTERVAL", 60))
        # 完整配置合法性校验
        if not self.ADMIN_TOKEN:
            logger.error("【OneAPI通用Token用量统计】未在后台配置OneAPI管理员Token，插件定时任务已禁用，请前往插件配置面板填写！")
            return
        if not self.ONE_API_URL:
            logger.error("【OneAPI通用Token用量统计】未配置OneAPI日志接口地址，插件定时任务已禁用！")
            return
        if self.FETCH_INTERVAL < 30:
            logger.warning("【OneAPI通用Token用量统计】日志拉取间隔低于30秒，频繁请求可能触发OneAPI限制！")
        self.last_log_id = 0
        self.db_path = "token_quota.db"
        self.init_sqlite_db()
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(
            self.fetch_oneapi_log_task,
            "interval",
            seconds=self.FETCH_INTERVAL
        )
        self.scheduler.start()
        logger.info(f"OneAPI通用Token用量统计插件已加载，目标令牌：{self.TARGET_TOKEN_NAME}，拉取间隔：{self.FETCH_INTERVAL}秒")

    def init_sqlite_db(self):
        """
        初始化本地SQLite数据库
        数据表字段说明：
        log_id: OneAPI日志唯一ID，主键，防止重复插入数据
        create_ts: 日志生成的秒级时间戳
        token_name: 产生扣费的令牌名称
        consume_quota: 本次接口调用消耗的Token数量
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS quota_log (
                log_id INTEGER PRIMARY KEY,
                create_ts INTEGER NOT NULL,
                token_name TEXT NOT NULL,
                consume_quota INTEGER NOT NULL
            )
            ''')

    async def fetch_oneapi_log_task(self):
        """定时任务核心函数：请求OneAPI接口，拉取新增扣费日志并存入本地数据库"""
        headers = {"Authorization": f"Bearer {self.ADMIN_TOKEN}"}
        try:
            # 异步请求，不会阻塞机器人主线程
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.get(self.ONE_API_URL, headers=headers, timeout=timeout) as resp:
                    # 判断HTTP状态码
                    if resp.status != 200:
                        logger.warning(f"OneAPI接口请求异常，状态码：{resp.status}")
                        return
                    # 捕获非标准JSON返回
                    try:
                        res_data = await resp.json()
                    except aiohttp.ContentTypeError:
                        logger.error("OneAPI接口返回内容不是JSON格式")
                        return
                    if not res_data.get("success"):
                        logger.warning(f"OneAPI接口返回失败：{res_data}")
                        return
        except Exception as e:
            logger.error(f"拉取OneAPI日志网络异常: {str(e)}")
            return

        log_list = res_data["data"]
        new_max_id = self.last_log_id

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for item in log_list:
                log_id = item["id"]
                # type=2 代表OneAPI扣费日志，仅统计扣费记录
                if log_id > self.last_log_id and item["type"] == 2 and item["token_name"] == self.TARGET_TOKEN_NAME:
                    cursor.execute('''
                    INSERT OR IGNORE INTO quota_log (log_id, create_ts, token_name, consume_quota)
                    VALUES (?, ?, ?, ?)
                    ''', (log_id, item["created_at"], item["token_name"], item["quota"]))
                    if log_id > new_max_id:
                        new_max_id = log_id

        self.last_log_id = new_max_id

    @filter.command("token额度")
    async def query_today_quota(self, event: AstrMessageEvent):
        """
        聊天指令：/token额度
        功能：查询今日选定令牌总共消耗的Token额度
        """
        # 使用UTC时间统一分界，避免时区错位
        now_utc = datetime.now(timezone.utc)
        today_utc_start = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
        today_start_ts = int(today_utc_start.timestamp())

        total_quota = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT SUM(consume_quota) FROM quota_log
            WHERE token_name = ? AND create_ts >= ?
            ''', (self.TARGET_TOKEN_NAME, today_start_ts))
            res = cursor.fetchone()
            if res[0] is not None:
                total_quota = res[0]

        msg = f"📊 今日【{self.TARGET_TOKEN_NAME}】令牌总消耗额度：{total_quota} token"
        yield event.plain_result(msg)

    @filter.command("额度帮助")
    async def plugin_help_info(self, event: AstrMessageEvent):
        """
        聊天指令：/额度帮助
        功能：查看插件配置帮助文档
        """
        help_text = """
📖 OneAPI通用Token用量统计插件 使用帮助
⚠️ 前置依赖：服务器必须提前部署并正常运行 OneAPI 服务，插件依赖OneAPI日志接口获取扣费数据。
===== 配置修改方式 =====
前往 AstrBot 后台本插件的【配置】面板可视化填写参数：
1. OneAPI管理员Token：你的OneAPI后台管理员密钥
2. OneAPI日志接口地址：Docker容器默认 http://oneapi:3000/api/log/search
3. 需要统计的OneAPI令牌名称：和OneAPI后台令牌名称保持一致
4. 日志拉取间隔：单位秒，最小30秒，推荐60秒
===== 可用聊天指令 =====
/token额度  查看当日选定令牌全局消耗token数量
/额度帮助  查看本插件配置帮助文档
        """
        yield event.plain_result(help_text)
