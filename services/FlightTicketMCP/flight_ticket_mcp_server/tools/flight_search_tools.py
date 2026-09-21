"""
Flight Search Tools - 航班路线查询工具

提供根据出发地、目的地和出发日期查询航班路线的功能

浏览器模拟策略：
- 每次请求创建全新的浏览器实例（不同指纹）
- 随机 User-Agent
- 随机窗口大小
- 随机请求延迟
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import json
import random
import logging
import time
import re

# 初始化日志器
logger = logging.getLogger(__name__)

# 导入DrissionPage（可选）
try:
    from DrissionPage import ChromiumPage, ChromiumOptions
    DRISSION_PAGE_AVAILABLE = True
except ImportError:
    logger.warning("DrissionPage未安装，航班路线查询功能将不可用")
    ChromiumPage = None
    ChromiumOptions = None
    DRISSION_PAGE_AVAILABLE = False

# 导入城市字典
try:
    from ..utils.cities_dict import get_airport_code, get_city_name
except ImportError:
    logger.warning("城市字典未找到，航班路线查询功能将不可用")
    get_airport_code = None
    get_city_name = None


# =================== 反检测配置 ===================

# 常用 User-Agent 列表（模拟不同浏览器/系统）
USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    # Safari on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]

# 常用窗口尺寸（模拟不同显示器）
WINDOW_SIZES = [
    (1920, 1080),  # Full HD
    (1366, 768),   # 常见笔记本
    (1536, 864),   # 常见笔记本
    (1440, 900),   # MacBook
    (1680, 1050),  # 大显示器
    (2560, 1440),  # 2K 显示器
    (1280, 720),   # HD
]

# 常用语言设置
LANGUAGES = [
    "zh-CN,zh;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.9",
    "zh-CN,zh-TW;q=0.9,zh;q=0.8,en;q=0.7",
]

# 浏览器用户数据目录（用于持久化 Cookie 和会话，绕过验证码）
import os
import sys

# =================== 浏览器自动检测 ===================

# 常见浏览器路径
BROWSER_PATHS = {
    'chrome': [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        r'C:\Users\{username}\AppData\Local\Google\Chrome\Application\chrome.exe',
    ],
    'edge': [
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    ],
    'chromium': [
        r'C:\Program Files\Chromium\Application\chrome.exe',
        r'C:\Program Files (x86)\Chromium\Application\chrome.exe',
    ],
}

def get_available_browser() -> tuple:
    """
    自动检测可用的 Chromium 内核浏览器

    优先级: Chrome > Edge > Chromium

    Returns:
        tuple: (浏览器名称, 浏览器路径) 或 (None, None) 如果没找到
    """
    import getpass
    username = getpass.getuser()

    configured_path = os.getenv('FLIGHT_BROWSER_PATH')
    if configured_path and os.path.exists(configured_path):
        return ('configured', configured_path)

    for browser_name, paths in BROWSER_PATHS.items():
        for path in paths:
            # 替换用户名占位符
            actual_path = path.replace('{username}', username)
            if os.path.exists(actual_path):
                logger.info(f"检测到可用浏览器: {browser_name} -> {actual_path}")
                return (browser_name, actual_path)

    logger.warning("未检测到任何可用的 Chromium 内核浏览器 (Chrome/Edge/Chromium)")
    return (None, None)

# 在模块加载时检测可用浏览器
DETECTED_BROWSER_NAME, DETECTED_BROWSER_PATH = get_available_browser()


def get_browser_data_dir():
    """
    获取浏览器用户数据目录路径

    支持两种环境：
    1. 开发环境：使用项目目录下的 browser_data
    2. 打包环境（PyInstaller）：使用 exe 所在目录下的 browser_data
    """
    if getattr(sys, 'frozen', False):
        # 打包环境：使用 exe 所在目录
        base_dir = os.path.dirname(sys.executable)
        logger.info(f"[打包环境] exe 目录: {base_dir}")
    else:
        # 开发环境：使用项目根目录（flight_ticket_mcp_server 的上级）
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        base_dir = os.path.abspath(base_dir)  # 规范化路径
        logger.debug(f"[开发环境] 项目目录: {base_dir}")

    browser_data_dir = os.path.join(base_dir, "browser_data")
    browser_data_dir = os.path.abspath(browser_data_dir)  # 规范化路径

    # 确保目录存在
    try:
        os.makedirs(browser_data_dir, exist_ok=True)
        logger.info(f"浏览器数据目录: {browser_data_dir}")
    except PermissionError:
        # 没有写入权限，回退到用户主目录
        logger.warning(f"无法在 {browser_data_dir} 创建目录（权限不足），使用用户主目录")
        browser_data_dir = os.path.join(os.path.expanduser("~"), ".flight_mcp_browser_data")
        os.makedirs(browser_data_dir, exist_ok=True)
        logger.info(f"浏览器数据目录（回退）: {browser_data_dir}")
    except Exception as e:
        # 其他错误，也回退到用户主目录
        logger.warning(f"创建浏览器数据目录失败: {e}，使用用户主目录")
        browser_data_dir = os.path.join(os.path.expanduser("~"), ".flight_mcp_browser_data")
        try:
            os.makedirs(browser_data_dir, exist_ok=True)
        except:
            pass  # 如果还失败，后续使用时会报错
        logger.info(f"浏览器数据目录（回退）: {browser_data_dir}")

    return browser_data_dir

BROWSER_USER_DATA_DIR = get_browser_data_dir()


def create_browser_options(headless: bool = True, use_user_data: bool = True) -> 'ChromiumOptions':
    """
    创建带有随机反检测配置的浏览器选项

    每次调用都会生成不同的浏览器指纹，模拟不同用户
    自动检测并使用可用的浏览器（Chrome/Edge/Chromium）

    Args:
        headless: 是否使用无头模式
        use_user_data: 是否使用持久化用户数据目录（保存Cookie绕过验证码）

    Returns:
        配置好的 ChromiumOptions 对象
    """
    co = ChromiumOptions()

    # 【关键】设置浏览器路径 - 支持 Chrome/Edge/Chromium
    if DETECTED_BROWSER_PATH:
        co.set_browser_path(DETECTED_BROWSER_PATH)
        logger.info(f"使用浏览器: {DETECTED_BROWSER_NAME} ({DETECTED_BROWSER_PATH})")
    else:
        logger.warning("未检测到浏览器，使用默认配置（可能会失败）")

    # 使用持久化用户数据目录（关键：保存 Cookie 和会话，绕过验证码）
    if use_user_data:
        co.set_argument(f'--user-data-dir={BROWSER_USER_DATA_DIR}')
        logger.debug(f"使用用户数据目录: {BROWSER_USER_DATA_DIR}")

    # 随机选择 User-Agent
    user_agent = random.choice(USER_AGENTS)
    co.set_user_agent(user_agent)
    logger.debug(f"使用 User-Agent: {user_agent[:50]}...")

    # 随机选择窗口大小
    width, height = random.choice(WINDOW_SIZES)
    co.set_argument(f'--window-size={width},{height}')
    logger.debug(f"使用窗口大小: {width}x{height}")

    # 随机选择语言
    lang = random.choice(LANGUAGES)
    co.set_argument(f'--lang={lang.split(",")[0]}')

    # 禁用自动化检测标志（核心反检测）
    co.set_argument('--disable-blink-features=AutomationControlled')

    # 禁用沙盒模式（提高兼容性）
    co.set_argument('--no-sandbox')

    # 禁用开发者扩展
    co.set_argument('--disable-extensions')

    # 禁用 GPU（无头模式下更稳定）
    co.set_argument('--disable-gpu')

    # 禁用日志输出
    co.set_argument('--log-level=3')
    co.set_argument('--silent')

    # 禁用信息栏
    co.set_argument('--disable-infobars')

    # 禁用通知
    co.set_argument('--disable-notifications')

    # 禁用弹窗阻止
    co.set_argument('--disable-popup-blocking')

    # 设置随机的时区偏移（模拟不同地区用户）
    # 注意：这个参数可能需要根据实际情况调整

    if headless:
        co.headless()

    return co











# =================== 航班路线查询功能 ===================

class FlightRouteSearcher:
    """
    航班路线查询器

    浏览器模拟策略：
    - 每次 search_flights 调用都创建全新的浏览器实例
    - 每个浏览器实例有不同的指纹（User-Agent、窗口大小等）
    - 查询完成后立即关闭浏览器，避免同一浏览器发送多个请求
    """

    def __init__(self, headless=True):
        """
        初始化查询器（不再预创建浏览器）

        Args:
            headless: 是否使用无头模式
        """
        if not DRISSION_PAGE_AVAILABLE:
            raise ImportError("DrissionPage库未安装，无法使用航班路线查询功能")

        self.headless = headless
        self.base_url = "https://flights.ctrip.com/online/list/oneway-{}-{}?_=1&depdate={}&cabin=Y_S_C_F"
        self.page = None  # 延迟创建

        logger.info("航班路线查询器初始化完成（每次请求将创建新浏览器实例）")

    def _create_new_browser(self):
        """
        创建全新的浏览器实例

        每次调用都会生成不同的浏览器指纹，模拟不同用户访问
        """
        # 关闭旧的浏览器（如果存在）
        if self.page:
            try:
                self.page.quit()
            except:
                pass

        try:
            # 创建带有随机配置的新浏览器
            logger.info("正在创建浏览器实例...")
            co = create_browser_options(self.headless)

            try:
                self.page = ChromiumPage(co)
            except Exception as browser_error:
                error_msg = str(browser_error).lower()
                logger.error(f"创建浏览器实例失败: {browser_error}")

                # 检测是否是文件锁问题
                if 'lock' in error_msg or 'singleton' in error_msg or 'in use' in error_msg:
                    logger.warning("检测到浏览器用户数据目录被锁定！")
                    logger.warning("可能的原因：")
                    logger.warning("  1. 有其他 Chrome/Edge 进程正在使用该目录")
                    logger.warning("  2. 上次浏览器崩溃，留下了锁文件")
                    logger.warning("建议操作：")
                    logger.warning("  1. 在主界面点击「启动服务」时选择「清除Cookie」")
                    logger.warning("  2. 或手动关闭所有 Chrome/Edge 进程后重试")

                logger.info("尝试使用默认配置创建浏览器（不使用用户数据目录）...")

                # 尝试不使用用户数据目录
                co_fallback = create_browser_options(self.headless, use_user_data=False)
                self.page = ChromiumPage(co_fallback)
                logger.warning("使用默认配置创建浏览器成功（Cookie 将不会被保存，可能需要重新验证）")

            # 添加随机延迟，模拟真实用户行为
            delay = random.uniform(0.5, 1.5)
            time.sleep(delay)

            logger.info("浏览器实例创建成功")

        except Exception as e:
            logger.error(f"创建浏览器失败: {e}")
            raise RuntimeError(f"无法创建浏览器实例: {e}")
    
    def search_flights(self, departure_city: str, destination_city: str, departure_date: str) -> List[Dict[str, Any]]:
        """
        搜索航班

        每次搜索都会创建全新的浏览器实例

        Args:
            departure_city: 出发城市
            destination_city: 目的地城市
            departure_date: 出发日期 (YYYY-MM-DD格式)

        Returns:
            航班信息列表
        """
        logger.info(f"开始搜索航班：{departure_city} -> {destination_city}, 日期：{departure_date}")

        # 获取机场代码
        departure_code = get_airport_code(departure_city)
        destination_code = get_airport_code(destination_city)

        if not departure_code or not destination_code:
            logger.warning(f"无法找到机场代码：出发地={departure_city}, 目的地={destination_city}")
            return []

        # 验证日期格式
        try:
            datetime.strptime(departure_date, '%Y-%m-%d')
        except ValueError:
            logger.warning(f"日期格式错误: {departure_date}")
            return []

        # 构建搜索URL
        search_url = self.base_url.format(departure_code, destination_code, departure_date)

        logger.info(f"搜索URL: {search_url}")
        logger.info(f"出发地：{get_city_name(departure_city)} ({departure_code.upper()})")
        logger.info(f"目的地：{get_city_name(destination_city)} ({destination_code.upper()})")

        try:
            # 【关键】每次搜索创建全新的浏览器实例
            logger.info("创建新浏览器实例...")
            self._create_new_browser()

            # 访问页面
            self.page.get(search_url)
            logger.info("页面加载完成，等待内容渲染...")

            # 携程 WhaleGuard 可能直接返回只有 "whaleguard block" 的拦截页。
            # 这不是“没有航班”，必须向上层报告数据源不可用。
            initial_html = (self.page.html or "").lower()
            if "whaleguard block" in initial_html:
                raise RuntimeError("携程 WhaleGuard 已拦截当前网络/IP，请更换网络或完成验证")

            # 检测是否有验证码或需要登录
            needs_action, action_type = self._detect_captcha_or_login()
            if needs_action:
                if action_type == 'login':
                    logger.warning("检测到需要登录！打开浏览器让用户登录...")
                else:
                    logger.warning("检测到验证码！尝试使用非无头模式让用户手动处理...")

                # 关闭当前浏览器
                self.page.quit()
                self.page = None

                # 使用非无头模式重新创建浏览器，传递操作类型
                self._create_new_browser_for_captcha(search_url, action_type or 'captcha')

                # 再次检测是否已处理
                needs_action_again, _ = self._detect_captcha_or_login()
                if needs_action_again:
                    raise RuntimeError("携程验证码/登录仍未处理，无法继续查询")

            # 智能滚动加载更多内容
            self._intelligent_scroll_for_content()

            # 智能等待页面加载完成
            self._wait_for_page_ready()

            # 等待关键元素出现
            self._wait_for_flight_content()

            # 解析航班信息
            flights = self._parse_flights()

            logger.info(f"搜索完成，找到 {len(flights)} 条航班信息")
            return flights

        except Exception as e:
            logger.error(f"搜索航班失败: {str(e)}", exc_info=True)
            raise

        finally:
            # 【关键】搜索完成后立即关闭浏览器，释放资源
            if self.page:
                try:
                    self.page.quit()
                    self.page = None
                    logger.debug("浏览器实例已关闭")
                except:
                    pass

    def _detect_captcha_or_login(self) -> tuple:
        """
        检测页面是否有验证码或需要登录

        Returns:
            tuple: (需要处理, 类型) - 类型可以是 'captcha', 'login', 或 None
        """
        time.sleep(2)  # 等待页面加载

        # 检查常见的验证码元素
        captcha_selectors = [
            'css:.captcha',
            'css:#captcha',
            'css:.verify',
            'css:#verify',
            'css:.slide-verify',
            'css:.nc-container',  # 阿里云滑块验证
            'css:#nc_1_wrapper',
            'css:.geetest',  # 极验验证码
        ]

        for selector in captcha_selectors:
            try:
                element = self.page.ele(selector, timeout=1)
                if element:
                    logger.warning(f"检测到验证码元素: {selector}")
                    return (True, 'captcha')
            except:
                pass

        # 检查是否需要登录
        login_selectors = [
            'css:.login-btn',
            'css:#login',
            'css:.login-box',
            'css:.login-form',
            'css:.signin',
            'css:[data-ubt="login_btn"]',
        ]

        for selector in login_selectors:
            try:
                element = self.page.ele(selector, timeout=1)
                if element:
                    logger.warning(f"检测到登录元素: {selector}")
                    return (True, 'login')
            except:
                pass

        # 检查页面内容是否包含验证或登录相关文字
        try:
            page_text = self.page.html[:5000].lower()

            # 先检查是否有航班内容，如果有就不需要处理
            flight_items = self.page.eles('css:.flight-item', timeout=1)
            if len(flight_items) > 0:
                return (False, None)

            # 检查验证码关键字
            captcha_keywords = ['验证', 'verify', 'captcha', '滑动', '安全验证', 'whaleguard block']
            for keyword in captcha_keywords:
                if keyword in page_text:
                    logger.warning(f"页面包含验证关键字: {keyword}")
                    return (True, 'captcha')

            # 检查登录关键字
            login_keywords = ['请登录', '立即登录', '登录后', 'sign in', 'login']
            for keyword in login_keywords:
                if keyword in page_text:
                    logger.warning(f"页面包含登录关键字: {keyword}")
                    return (True, 'login')
        except:
            pass

        return (False, None)

    def _detect_captcha(self) -> bool:
        """
        检测页面是否有验证码（兼容旧接口）

        Returns:
            True 如果检测到验证码或需要登录
        """
        needs_action, _ = self._detect_captcha_or_login()
        return needs_action

    def _check_page_abnormal(self):
        """
        检查页面是否异常（验证码、无航班提示、错误页面等）
        如果发现异常，记录详细日志
        """
        try:
            page_text = self.page.html.lower()

            # 检查验证码
            captcha_keywords = ['验证', 'verify', 'captcha', '滑动', '安全验证', '人机验证', 'whaleguard block']
            for keyword in captcha_keywords:
                if keyword in page_text:
                    logger.warning(f"⚠️ 页面检测到验证码关键字: {keyword}")
                    logger.warning("💡 建议：下次启动时选择「清除Cookie」，首次查询会弹出浏览器让您手动验证")
                    return

            # 检查无航班提示
            no_flight_keywords = ['暂无航班', '没有找到', '未找到航班', 'no flight', '无搜索结果']
            for keyword in no_flight_keywords:
                if keyword in page_text:
                    logger.info(f"ℹ️ 页面提示: {keyword}（可能该航线确实无航班）")
                    return

            # 检查登录要求
            login_keywords = ['请登录', '立即登录', '登录后', 'sign in', 'login']
            for keyword in login_keywords:
                if keyword in page_text:
                    logger.warning(f"⚠️ 页面要求登录: {keyword}")
                    return

            # 检查错误页面
            error_keywords = ['页面不存在', '404', '500', '系统错误', 'error', '访问受限']
            for keyword in error_keywords:
                if keyword in page_text:
                    logger.error(f"❌ 页面错误: {keyword}")
                    return

            # 未找到明确原因
            logger.warning("❓ 未找到航班，且无法确定具体原因")
            logger.info(f"当前页面URL: {self.page.url}")

        except Exception as e:
            logger.debug(f"页面异常检查出错: {e}")

    def _create_new_browser_for_captcha(self, url: str, action_type: str = 'captcha'):
        """
        创建非无头模式浏览器让用户手动处理验证码或登录

        Args:
            url: 要访问的URL
            action_type: 需要的操作类型 ('captcha' 或 'login')
        """
        if action_type == 'login':
            logger.info("创建可视化浏览器窗口，请登录携程账号...")
        else:
            logger.info("创建可视化浏览器窗口，请手动完成验证码...")

        # 创建非无头模式的浏览器
        co = create_browser_options(headless=False, use_user_data=True)
        self.page = ChromiumPage(co)

        # 访问页面
        self.page.get(url)

        # 等待页面加载或用户处理验证码/登录（最多等待120秒，给用户足够时间）
        logger.info("=" * 50)
        if action_type == 'login':
            logger.info("⚠️ 请在弹出的浏览器窗口中登录携程账号！")
            logger.info("⚠️ 登录后 Cookie 将被保存，下次无需重复登录")
        else:
            logger.info("⚠️ 请在弹出的浏览器窗口中完成验证码验证！")
        logger.info("⚠️ 操作完成后，航班数据将自动加载")
        logger.info("⚠️ 最多等待 120 秒，请耐心操作...")
        logger.info("=" * 50)

        min_flight_count = 3  # 至少要有3个航班才认为加载成功
        consecutive_success_needed = 2  # 连续2次检测到航班才确认成功
        consecutive_success = 0

        for i in range(120):  # 增加到120秒
            time.sleep(1)

            # 检查是否有航班列表出现
            try:
                flight_items = self.page.eles('css:.flight-item', timeout=1)
                if len(flight_items) >= min_flight_count:
                    consecutive_success += 1
                    if consecutive_success >= consecutive_success_needed:
                        logger.info(f"✅ 页面加载成功，检测到 {len(flight_items)} 个航班")
                        # 额外等待确保数据完全加载
                        time.sleep(3)
                        return
                    else:
                        logger.info(f"检测到 {len(flight_items)} 个航班，等待确认...")
                else:
                    consecutive_success = 0  # 重置计数器
            except:
                consecutive_success = 0
                pass

            # 每15秒输出一次提示
            if i > 0 and i % 15 == 0:
                logger.info(f"⏳ 仍在等待处理... ({i}/120秒)")
                if action_type == 'login':
                    logger.info("💡 提示：请在浏览器窗口中完成登录")
                else:
                    logger.info("💡 提示：请在浏览器窗口中完成验证码")

        logger.warning("⚠️ 页面加载超时（120秒），请检查网络或手动刷新页面")

    def _detect_captcha_fast(self) -> bool:
        """
        快速检测验证码（不包含 sleep）

        Returns:
            True 如果检测到验证码
        """
        # 检查常见的验证码元素
        captcha_selectors = [
            'css:.captcha',
            'css:#captcha',
            'css:.verify',
            'css:#verify',
            'css:.slide-verify',
            'css:.nc-container',
            'css:#nc_1_wrapper',
            'css:.geetest',
        ]

        for selector in captcha_selectors:
            try:
                element = self.page.ele(selector, timeout=0.5)
                if element:
                    logger.warning(f"检测到验证码元素: {selector}")
                    return True
            except:
                pass

        return False

    def _intelligent_scroll_for_content(self):
        """智能滚动以加载更多航班内容"""
        logger.debug("智能滚动加载航班内容...")

        try:
            # 先向下滚动几次，加载初始内容
            scroll_distances = [500, 800, 1200]

            for i, distance in enumerate(scroll_distances, 1):
                self.page.scroll(distance)
                logger.debug(f"第{i}次向下滚动 {distance}px")
                time.sleep(1.5)  # 等待内容加载

                # 检查是否有新的航班元素加载出来
                flight_elements = self.page.eles('css:.flight-item', timeout=1)
                logger.debug(f"当前页面航班元素数量：{len(flight_elements)}")

            # 滚动回到顶部，确保能看到所有航班
            logger.debug("滚动回到页面顶部")
            self.page.scroll(-2000)  # 向上滚动回到顶部
            time.sleep(1)

        except Exception as e:
            logger.warning(f"智能滚动过程中出错：{e}")
    def _wait_for_flight_content(self, timeout=30):
        """等待航班内容加载"""
        logger.debug("等待航班内容加载...")

        # 方法1：等待航班容器出现
        flight_container = self.page.ele('css:.body-wrapper', timeout=timeout)
        if flight_container:
            logger.debug("找到航班容器")

            # 方法2：等待航班列表出现
            flight_items = self.page.ele('css:.flight-item', timeout=10)
            if flight_items:
                logger.debug("航班列表加载完成")
            else:
                logger.debug("等待航班列表超时，尝试其他解析方法...")

                # 等待可能的加载指示器消失
                self._wait_for_loading_complete()
        else:
            logger.warning("航班容器未找到")
    def _wait_for_page_ready(self, timeout=30):
        """智能等待页面完全加载"""
        logger.debug("等待页面完全加载...")

        # 方法1：等待 document.readyState 为 complete
        start_time = time.time()
        while time.time() - start_time < timeout:
            ready_state = self.page.run_js("return document.readyState")
            if ready_state == "complete":
                logger.debug("页面DOM加载完成")
                break
            time.sleep(0.5)
        else:
            logger.debug("页面加载超时，继续执行...")

        # 方法2：等待jQuery加载完成（如果页面使用jQuery）
        if self._wait_for_jquery_ready():
            logger.debug("jQuery加载完成")

        # 方法3：等待Ajax请求完成
        if self._wait_for_ajax_complete():
            logger.debug("Ajax请求完成")

    def _wait_for_ajax_complete(self, timeout=10):
        """等待Ajax请求完成"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # 检查是否有活跃的Ajax请求
                ajax_complete = self.page.run_js("""
                    if (typeof XMLHttpRequest !== 'undefined') {
                        return XMLHttpRequest.active === 0 || XMLHttpRequest.active === undefined;
                    }
                    return true;
                """)
                if ajax_complete:
                    return True
            except:
                pass
            time.sleep(0.2)
        return False

    def _wait_for_jquery_ready(self, timeout=10):
        """等待jQuery加载完成"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                jquery_active = self.page.run_js("return typeof jQuery !== 'undefined' && jQuery.active === 0")
                if jquery_active:
                    return True
            except:
                pass
            time.sleep(0.2)
        return False
    def _wait_for_loading_complete(self, timeout=15):
        """等待加载指示器消失"""
        logger.debug("等待加载指示器消失...")

        # 常见的加载指示器选择器
        loading_selectors = [
            '.loading',
            '.spinner',
            '.loader',
            '#loading',
            '[data-loading]',
            '.fa-spinner',
            '.loading-overlay'
        ]

        for selector in loading_selectors:
            try:
                # 等待加载指示器消失
                start_time = time.time()
                while time.time() - start_time < timeout:
                    loader = self.page.ele(f'css:{selector}', timeout=1)
                    if not loader:
                        break
                    time.sleep(0.5)
                else:
                    continue
                logger.debug(f"加载指示器 {selector} 已消失")
                break
            except:
                continue

    def _parse_flights(self) -> List[Dict[str, Any]]:
        """解析航班信息"""
        flights = []

        try:
            # 查找航班容器
            flight_list = self.page.ele('css:.body-wrapper')
            if not flight_list:
                logger.warning("未找到航班容器")
                # 【增强】检查是否遇到异常页面
                self._check_page_abnormal()
                return []

            # 查找航班项
            flight_containers = flight_list.eles('css:.flight-item')
            if not flight_containers:
                logger.warning("未找到航班项")
                # 【增强】检查是否遇到异常页面（验证码、无航班提示等）
                self._check_page_abnormal()
                return []

            logger.info(f"找到 {len(flight_containers)} 个航班容器")

            # 选取存在航班号的10个航班
            valid_flights_count = 0
            for i, container in enumerate(flight_containers):
                if valid_flights_count >= 10:  # 已找到10个有效航班，停止搜索
                    break

                try:
                    flight_info = self._parse_flight_container(container, i + 1)
                    if flight_info and flight_info.get('航班号') and flight_info.get('航班号') != '未知':
                        # 只有当航班号存在且不是'未知'时才添加
                        flights.append(flight_info)
                        valid_flights_count += 1
                        logger.debug(f"成功解析航班 {valid_flights_count}: {flight_info.get('航班号')}")
                    else:
                        logger.debug(f"航班容器 {i+1} 无有效航班号，跳过")

                except Exception as e:
                    logger.error(f"解析航班容器 {i+1} 出错: {str(e)}")
                    continue

            logger.info(f"成功找到 {valid_flights_count} 个有航班号的航班")
            return flights
            
        except Exception as e:
            logger.error(f"解析航班信息失败: {str(e)}", exc_info=True)
            return []
    
    def _parse_flight_container(self, container, index: int) -> Optional[Dict[str, Any]]:
        """
        解析单个航班容器（支持直达和中转航班）

        Args:
            container: 航班容器元素
            index: 航班序号

        Returns:
            航班信息字典
        """
        flight_info = {'序号': index}

        try:
            # 解析航空公司
            airline_span = container.ele('css:.airline-name span', timeout=1)
            if airline_span:
                flight_info['航空公司'] = airline_span.text.strip()

            # 解析所有航班号（支持中转航班有多个航班号）
            plane_no_spans = container.eles('css:.plane-No', timeout=1)
            flight_numbers = []
            for span in plane_no_spans:
                plane_text = span.text.strip()
                # 提取航班号（如MU6863, CX337等）
                flight_match = re.search(r'([A-Z0-9]{2}\d{3,4})', plane_text)
                if flight_match:
                    flight_numbers.append(flight_match.group(1))

            if flight_numbers:
                if len(flight_numbers) == 1:
                    flight_info['航班号'] = flight_numbers[0]
                else:
                    # 多个航班号表示中转航班
                    flight_info['航班号'] = '/'.join(flight_numbers)
                    flight_info['航班号列表'] = flight_numbers

            # 检测航班类型：直达 or 中转
            arrow_transfer = container.ele('css:.arrow-transfer', timeout=1)
            if arrow_transfer:
                # 中转航班
                flight_info['航班类型'] = '中转'
                transfer_text = arrow_transfer.text.strip()
                # 提取中转次数（如"转1次"）
                transfer_match = re.search(r'转(\d+)次', transfer_text)
                if transfer_match:
                    flight_info['中转次数'] = int(transfer_match.group(1))
            else:
                # 直达航班（有 arrow-oneway 或没有 arrow-transfer）
                flight_info['航班类型'] = '直达'

            # 解析中转信息（中转城市和等待时间）
            transfer_info = container.ele('css:.transfer-info', timeout=1)
            if transfer_info:
                transfer_detail = transfer_info.text.strip()
                # 格式如: "转中国香港1h35m" 或 "转香港2h15m"
                # 提取中转城市和等待时间
                transfer_match = re.search(r'转(.+?)(\d+h\d+m|\d+小时\d+分钟?)', transfer_detail)
                if transfer_match:
                    flight_info['中转城市'] = transfer_match.group(1).strip()
                    flight_info['中转等待'] = transfer_match.group(2).strip()
                else:
                    # 尝试其他格式
                    flight_info['中转信息'] = transfer_detail

            # 解析总飞行时长
            flight_consume = container.ele('css:.flight-consume', timeout=1)
            if flight_consume:
                duration_text = flight_consume.text.strip()
                flight_info['总时长'] = duration_text
                # 提取小时和分钟数用于计算
                duration_match = re.search(r'(\d+)小时(\d+)分', duration_text)
                if duration_match:
                    hours = int(duration_match.group(1))
                    minutes = int(duration_match.group(2))
                    flight_info['总时长分钟'] = hours * 60 + minutes

            # 解析出发时间
            depart_time = container.ele('css:.depart-box .time', timeout=1)
            if depart_time:
                flight_info['出发时间'] = depart_time.text.strip()

            # 解析出发机场
            depart_airport = container.ele('css:.depart-box .name', timeout=1)
            if depart_airport:
                flight_info['出发机场'] = depart_airport.text.strip()

            # 解析出发航站楼
            depart_terminal = container.ele('css:.depart-box .terminal', timeout=1)
            if depart_terminal:
                flight_info['出发航站楼'] = depart_terminal.text.strip()

            # 解析到达时间
            arrive_time = container.ele('css:.arrive-box .time', timeout=1)
            if arrive_time:
                arrival_text = arrive_time.text.strip()
                # 处理跨天信息
                if '+1天' in arrival_text or '+2天' in arrival_text:
                    flight_info['到达时间'] = arrival_text
                    # 提取跨天数
                    day_match = re.search(r'\+(\d+)天', arrival_text)
                    if day_match:
                        flight_info['跨天'] = int(day_match.group(1))
                else:
                    flight_info['到达时间'] = arrival_text

            # 解析到达机场
            arrive_airport = container.ele('css:.arrive-box .name', timeout=1)
            if arrive_airport:
                flight_info['到达机场'] = arrive_airport.text.strip()

            # 解析到达航站楼
            arrive_terminal = container.ele('css:.arrive-box .terminal', timeout=1)
            if arrive_terminal:
                flight_info['到达航站楼'] = arrive_terminal.text.strip()

            # 解析价格
            price_span = container.ele('css:.price', timeout=1)
            if price_span:
                price_text = price_span.text.strip()
                # 处理价格格式
                if '¥' in price_text:
                    flight_info['价格'] = price_text
                    # 提取纯数字价格用于排序
                    price_num_match = re.search(r'(\d+)', price_text)
                    if price_num_match:
                        flight_info['价格数值'] = int(price_num_match.group(1))
                else:
                    # 提取数字价格
                    price_match = re.search(r'(\d+)', price_text)
                    if price_match:
                        flight_info['价格'] = f"¥{price_match.group(1)}"
                        flight_info['价格数值'] = int(price_match.group(1))

            # 检查是否有足够的信息
            if any(key in flight_info for key in ['航班号', '出发时间', '价格']):
                return flight_info
            else:
                logger.debug(f"航班 {index} 缺少必要信息")
                return None

        except Exception as e:
            logger.error(f"解析航班容器 {index} 详细信息失败: {str(e)}")
            return None
    
    def close(self):
        """关闭浏览器（如果还有运行中的实例）"""
        if self.page:
            try:
                self.page.quit()
                self.page = None
                logger.info("浏览器已关闭")
            except Exception as e:
                logger.debug(f"关闭浏览器时出错: {e}")


def searchFlightRoutes(departure_city: str, destination_city: str, departure_date: str) -> Dict[str, Any]:
    """
    根据出发地、目的地和出发日期查询航班路线

    Args:
        departure_city: 出发城市名称或机场代码
        destination_city: 目的地城市名称或机场代码
        departure_date: 出发日期 (YYYY-MM-DD格式)

    Returns:
        包含航班查询结果的字典
    """
    logger.info(f"开始查询航班路线: {departure_city} -> {destination_city}, 日期: {departure_date}")

    try:
        # 验证输入参数
        if not departure_city or not destination_city or not departure_date:
            logger.warning("参数不完整")
            return {
                "status": "error",
                "message": "出发地、目的地和出发日期都不能为空",
                "error_code": "INVALID_PARAMS"
            }
        
        # 检查依赖是否可用
        if not DRISSION_PAGE_AVAILABLE:
            logger.error("DrissionPage库未安装")
            return {
                "status": "error",
                "message": "DrissionPage库未安装，无法进行航班搜索",
                "error_code": "DRISSION_PAGE_NOT_AVAILABLE"
            }
        
        if not get_airport_code or not get_city_name:
            logger.error("城市字典未找到")
            return {
                "status": "error",
                "message": "城市字典未找到，无法进行航班搜索",
                "error_code": "CITIES_DICT_NOT_AVAILABLE"
            }
        
        # 验证日期格式
        try:
            flight_date = datetime.strptime(departure_date, "%Y-%m-%d")
            logger.debug(f"日期解析成功: {flight_date}")
        except ValueError:
            logger.warning(f"日期格式错误: {departure_date}")
            return {
                "status": "error",
                "message": "日期格式不正确，请使用YYYY-MM-DD格式",
                "error_code": "INVALID_DATE_FORMAT"
            }
        
        # 检查日期是否为过去的日期
        if flight_date.date() < datetime.now().date():
            logger.warning(f"查询过去的日期: {departure_date}")
            return {
                "status": "error",
                "message": "不能查询过去的日期",
                "error_code": "PAST_DATE"
            }
        
        # 验证城市/机场代码
        if not get_airport_code(departure_city):
            logger.warning(f"无效的出发地: {departure_city}")
            return {
                "status": "error",
                "message": f"无效的出发地: {departure_city}",
                "error_code": "INVALID_DEPARTURE_CITY"
            }
        
        if not get_airport_code(destination_city):
            logger.warning(f"无效的目的地: {destination_city}")
            return {
                "status": "error",
                "message": f"无效的目的地: {destination_city}",
                "error_code": "INVALID_DESTINATION_CITY"
            }
        
        # 创建搜索器并搜索
        searcher = FlightRouteSearcher(headless=True)

        try:
            flights = searcher.search_flights(departure_city, destination_city, departure_date)

            # 格式化结果
            result = {
                "status": "success",
                "departure_city": departure_city,
                "destination_city": destination_city,
                "departure_date": departure_date,
                "departure_airport": get_city_name(departure_city),
                "destination_airport": get_city_name(destination_city),
                "flight_count": len(flights),
                "flights": flights,
                "formatted_output": _format_route_result(flights, departure_city, destination_city, departure_date),
                "query_time": datetime.now().isoformat()
            }
            
            # 添加统计信息
            if flights:
                prices = []
                airlines = {}
                
                for flight in flights:
                    # 提取价格
                    if '价格' in flight and flight['价格'] != '未知':
                        price_str = flight['价格'].replace('¥', '').replace('起', '')
                        if price_str.isdigit():
                            prices.append(int(price_str))
                    
                    # 统计航空公司
                    airline = flight.get('航空公司', '未知')
                    airlines[airline] = airlines.get(airline, 0) + 1
                
                if prices:
                    result["price_statistics"] = {
                        "min_price": min(prices),
                        "max_price": max(prices),
                        "avg_price": sum(prices) // len(prices)
                    }
                
                if airlines:
                    result["airline_statistics"] = airlines
            
            logger.info(f"航班路线查询成功: 找到 {len(flights)} 条航班")
            return result

        finally:
            searcher.close()

    except Exception as e:
        logger.error(f"查询航班路线失败: {str(e)}")
        return {
            "status": "error",
            "message": f"查询航班路线失败: {str(e)}",
            "error_code": "SEARCH_FAILED"
        }


def _format_route_result(flights: List[Dict[str, Any]], departure_city: str, destination_city: str, departure_date: str) -> str:
    """
    格式化航班路线查询结果
    
    Args:
        flights: 航班列表
        departure_city: 出发城市
        destination_city: 目的地城市
        departure_date: 出发日期
        
    Returns:
        格式化后的字符串
    """
    if not flights:
        return f"😔 未找到 {departure_city} -> {destination_city} 在 {departure_date} 的航班"
    
    output = []
    output.append(f"✈️ 航班查询结果")
    output.append(f"📍 {get_city_name(departure_city)} -> {get_city_name(destination_city)}")
    output.append(f"📅 {departure_date}")
    output.append(f"🔢 共找到 {len(flights)} 条航班")
    output.append("")
    
    # 显示航班列表
    for i, flight in enumerate(flights, 1):
        output.append(f"【{i}】{flight.get('航空公司', '未知')} {flight.get('航班号', '未知')}")
        output.append(f"    🛫 {flight.get('出发时间', '未知')} {flight.get('出发机场', '未知')} {flight.get('出发航站楼', '')}")
        output.append(f"    🛬 {flight.get('到达时间', '未知')} {flight.get('到达机场', '未知')} {flight.get('到达航站楼', '')}")
        output.append(f"    💰 {flight.get('价格', '未知')}")
        output.append("")
    
    return "\n".join(output) 
