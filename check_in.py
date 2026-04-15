# coding=UTF-8

import os
import sys
import json
import logging
import argparse
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from requests.utils import quote

# ---------- 配置日志 ----------
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

class V2FreeCheckIn:
    """使用 Playwright 模拟浏览器完成 V2Free 签到（支持 Cloudflare Turnstile）"""

    LOGIN_URL = "https://w2.v2free.top/auth/login"
    USER_URL = "https://w2.v2free.top/user"
    SIGN_URL = "https://w2.v2free.top/user/checkin"  # 实际签到接口，但我们用点击按钮方式

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.masked_username = self._mask_email(username)

    @staticmethod
    def _mask_email(email: str) -> str:
        """邮箱脱敏显示，如 1234567@qq.com -> 1******@q*.com"""
        at = email.rfind('@')
        dot = email.rfind('.')
        if at == -1 or dot == -1:
            return email
        local = email[0] + '*' * (at - 1)
        domain = email[at:at+2] + '*' * (dot - at - 2) + email[dot:]
        return local + domain

    def _send_notification(self, title: str, content: str):
        """通过 PushPlus 发送通知"""
        token = os.environ.get("PUSHPLUS_TOKEN", "")
        if not token:
            logging.warning("未设置 PUSHPLUS_TOKEN 环境变量，跳过通知")
            return
        url = f"https://www.pushplus.plus/send?token={token}&title={quote(title)}&content={quote(content)}"
        try:
            requests.get(url, timeout=10)
            logging.info("通知发送成功")
        except Exception as e:
            logging.error(f"通知发送失败: {e}")

    def run(self):
        """执行签到主流程"""
        with sync_playwright() as p:
            # 启动浏览器（无头模式）
            browser = p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']  # 隐藏自动化特征
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            try:
                # 1. 登录
                logging.info(f"正在登录 {self.masked_username} ...")
                page.goto(self.LOGIN_URL, wait_until="networkidle")
                page.fill("input[name='email']", self.username)
                page.fill("input[name='passwd']", self.password)
                page.click("button[type='submit']")

                # 等待登录成功跳转至 /user 页面，最长等待 15 秒
                page.wait_for_url(f"{self.USER_URL}*", timeout=15000)
                logging.info("登录成功！")

                # 2. 签到（通过点击页面上的签到按钮）
                page.goto(self.USER_URL, wait_until="networkidle")
                # 根据页面实际结构查找签到按钮（常见选择器）
                selectors = [
                    "button:has-text('签到')",
                    "a:has-text('签到')",
                    "button:has-text('每日签到')",
                    "#checkin-btn",  # 可能存在的 id
                ]
                clicked = False
                for sel in selectors:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        clicked = True
                        logging.info(f"点击签到按钮: {sel}")
                        break

                if not clicked:
                    # 如果找不到按钮，尝试直接 POST 签到接口（备用方案）
                    logging.warning("未找到签到按钮，尝试直接调用签到 API")
                    response = page.request.post(
                        self.SIGN_URL,
                        headers={"Referer": self.USER_URL}
                    )
                    result_text = response.text()
                else:
                    # 等待签到结果提示出现（假设会有 alert 或 toast 消息）
                    page.wait_for_timeout(2000)  # 等待 2 秒让结果渲染
                    # 尝试获取页面上的提示信息
                    result_selectors = [
                        ".alert", ".toast", ".message", "#checkin-result"
                    ]
                    result_text = ""
                    for rs in result_selectors:
                        loc = page.locator(rs)
                        if loc.count() > 0:
                            result_text = loc.first.inner_text()
                            break
                    if not result_text:
                        # 如果没获取到，尝试截取页面标题或 URL
                        result_text = f"页面标题: {page.title()}"

                logging.info(f"签到结果: {result_text}")

                # 3. 发送通知
                self._send_notification(
                    title=f"{self.masked_username} 签到结果",
                    content=json.dumps({"msg": result_text}, ensure_ascii=False)
                )

            except PlaywrightTimeoutError as e:
                error_msg = f"操作超时，可能账号密码错误或页面结构变更: {e}"
                logging.error(error_msg)
                self._send_notification(
                    title=f"{self.masked_username} 签到失败",
                    content=error_msg
                )
                sys.exit(1)
            except Exception as e:
                error_msg = f"签到过程异常: {e}"
                logging.exception(error_msg)
                self._send_notification(
                    title=f"{self.masked_username} 签到异常",
                    content=error_msg
                )
                sys.exit(1)
            finally:
                browser.close()

def main():
    parser = argparse.ArgumentParser(description="V2Free 自动签到脚本 (Playwright 版)")
    parser.add_argument("--username", type=str, help="登录邮箱")
    parser.add_argument("--password", type=str, help="登录密码")
    args = parser.parse_args()

    # 优先从环境变量读取账号密码
    username = os.environ.get("V2FREE_USERNAME") or args.username
    password = os.environ.get("V2FREE_PASSWORD") or args.password

    if not username or not password:
        logging.error("请通过环境变量 V2FREE_USERNAME / V2FREE_PASSWORD 或命令行参数提供账号密码")
        sys.exit(1)

    checker = V2FreeCheckIn(username, password)
    checker.run()

if __name__ == "__main__":
    main()
