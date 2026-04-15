# coding=UTF-8

import os
import sys
import json
import logging
import requests
from requests.utils import quote
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

class V2FreeCookieSign:
    USER_URL = "https://w2.v2free.top/user"

    def __init__(self, cookie_str: str):
        self.cookie_str = cookie_str.strip()
        self.masked_username = self._extract_email(cookie_str)
        # 将 cookie 字符串解析为 Playwright 可用的字典列表
        self.cookies = self._parse_cookies(cookie_str)

    @staticmethod
    def _parse_cookies(cookie_str: str):
        cookies = []
        for item in cookie_str.split(';'):
            item = item.strip()
            if not item or '=' not in item:
                continue
            name, value = item.split('=', 1)
            cookies.append({
                'name': name.strip(),
                'value': value.strip(),
                'domain': 'w2.v2free.top',
                'path': '/'
            })
        return cookies

    @staticmethod
    def _extract_email(cookie_str: str) -> str:
        """从 cookie 中提取邮箱用于显示"""
        try:
            for key in ['email', 'user_email', 'user']:
                if f'{key}=' in cookie_str:
                    start = cookie_str.find(f'{key}=') + len(key) + 1
                    end = cookie_str.find(';', start)
                    if end == -1:
                        end = len(cookie_str)
                    email = cookie_str[start:end]
                    at = email.rfind('@')
                    if at != -1:
                        return email[0] + '******' + email[at:at+2] + '***'
                    return email
        except:
            pass
        return "V2Free用户"

    def _send_notification(self, title: str, content: str):
        token = os.environ.get("PUSHPLUS_TOKEN", "")
        if not token:
            logging.warning("未设置 PUSHPLUS_TOKEN，跳过通知")
            return
        url = f"https://www.pushplus.plus/send?token={token}&title={quote(title)}&content={quote(content)}"
        try:
            requests.get(url, timeout=10)
            logging.info("通知已发送")
        except Exception as e:
            logging.error(f"通知发送失败: {e}")

    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="zh-CN",
                timezone_id="Asia/Shanghai"
            )
            # 注入 Cookie，实现免登录
            context.add_cookies(self.cookies)
            page = context.new_page()

            try:
                # 1. 直接进入用户中心
                logging.info(f"正在访问用户中心: {self.USER_URL}")
                page.goto(self.USER_URL, wait_until="networkidle", timeout=60000)

                # 2. 检查是否登录有效（若页面出现“登录”字样则 cookie 失效）
                if page.locator("text=登录").count() > 0:
                    raise Exception("Cookie 已失效，页面跳转到了登录页")

                logging.info("✅ 已通过 Cookie 成功登录，开始查找签到按钮...")

                # 3. 点击签到按钮
                sign_selectors = [
                    "button:has-text('签到')",
                    "a:has-text('签到')",
                    "button:has-text('每日签到')",
                    "#checkin-btn",
                    ".checkin-btn",
                ]
                clicked = False
                for sel in sign_selectors:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.click()
                        clicked = True
                        logging.info(f"已点击签到按钮: {sel}")
                        break

                if not clicked:
                    page.screenshot(path="no_sign_button.png")
                    result_text = "未找到签到按钮，可能今日已签到"
                else:
                    # 等待签到结果（Turnstile 验证会自动处理）
                    page.wait_for_timeout(5000)
                    
                    # 捕获结果文字
                    result_locators = [
                        ".alert", ".toast", ".message", "#checkin-result", ".swal2-content"
                    ]
                    result_text = ""
                    for loc_sel in result_locators:
                        el = page.locator(loc_sel)
                        if el.count() > 0:
                            result_text = el.first.inner_text()
                            break
                    if not result_text:
                        body_text = page.locator("body").inner_text()
                        if "签到成功" in body_text:
                            result_text = "签到成功"
                        elif "已经签到" in body_text:
                            result_text = "今日已签到"
                        else:
                            result_text = "操作已完成，请登录查看结果"

                logging.info(f"签到结果: {result_text}")
                self._send_notification(
                    title=f"{self.masked_username} 签到结果",
                    content=result_text
                )

                # 如果明确失败则退出码为 1
                if "失败" in result_text or "无法接受" in result_text:
                    sys.exit(1)

            except PlaywrightTimeoutError as e:
                error_msg = f"操作超时: {e}"
                logging.error(error_msg)
                page.screenshot(path="timeout_error.png")
                self._send_notification(title=f"{self.masked_username} 签到超时", content=error_msg)
                sys.exit(1)
            except Exception as e:
                error_msg = f"签到异常: {e}"
                logging.exception(error_msg)
                page.screenshot(path="exception_error.png")
                self._send_notification(title=f"{self.masked_username} 签到异常", content=error_msg)
                sys.exit(1)
            finally:
                browser.close()

def main():
    cookie = os.environ.get("V2FREE_COOKIE")
    if not cookie:
        logging.error("请设置环境变量 V2FREE_COOKIE")
        sys.exit(1)

    signer = V2FreeCookieSign(cookie)
    signer.run()

if __name__ == "__main__":
    main()
