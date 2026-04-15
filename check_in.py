# coding=UTF-8

import os
import sys
import json
import logging
import argparse
import time
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from requests.utils import quote

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

class V2FreeCheckIn:
    LOGIN_URL = "https://w2.v2free.top/auth/login"
    USER_URL = "https://w2.v2free.top/user"
    SIGN_URL = "https://w2.v2free.top/user/checkin"

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.masked_username = self._mask_email(username)

    @staticmethod
    def _mask_email(email: str) -> str:
        at = email.rfind('@')
        dot = email.rfind('.')
        if at == -1 or dot == -1:
            return email
        local = email[0] + '*' * (at - 1)
        domain = email[at:at+2] + '*' * (dot - at - 2) + email[dot:]
        return local + domain

    def _send_notification(self, title: str, content: str):
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

    def _wait_for_login_form(self, page, timeout=30000):
        """等待登录表单出现，支持多种可能的选择器"""
        selectors = [
            "input[name='email']",
            "input[name='username']",
            "input[type='email']",
            "#email",
            "#username",
        ]
        for sel in selectors:
            try:
                page.wait_for_selector(sel, timeout=5000)
                logging.info(f"找到邮箱输入框: {sel}")
                return sel
            except PlaywrightTimeoutError:
                continue
        raise Exception("无法找到邮箱输入框，页面可能被 Cloudflare 拦截或结构变更")

    def _wait_for_password_input(self, page, timeout=5000):
        """等待密码输入框"""
        selectors = [
            "input[name='passwd']",
            "input[name='password']",
            "input[type='password']",
            "#password",
        ]
        for sel in selectors:
            if page.locator(sel).count() > 0:
                logging.info(f"找到密码输入框: {sel}")
                return sel
        raise Exception("无法找到密码输入框")

    def run(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            try:
                # 访问登录页，等待网络空闲
                logging.info(f"正在访问登录页: {self.LOGIN_URL}")
                page.goto(self.LOGIN_URL, wait_until="networkidle", timeout=60000)
                
                # 检查是否被 Cloudflare 拦截（常见提示）
                cf_text = page.locator("body").inner_text()
                if "Checking your browser" in cf_text or "DDoS" in cf_text:
                    logging.error("页面被 Cloudflare 浏览器检查拦截，无法自动通过。")
                    # 保存截图以便调试
                    page.screenshot(path="cf_challenge.png")
                    logging.info("已保存截图 cf_challenge.png")
                    raise Exception("Cloudflare 拦截，无法继续")

                # 等待登录表单出现
                email_selector = self._wait_for_login_form(page)
                pass_selector = self._wait_for_password_input(page)

                # 填写账号密码
                logging.info(f"正在登录 {self.masked_username} ...")
                page.fill(email_selector, self.username)
                page.fill(pass_selector, self.password)

                # 点击登录按钮（同样尝试多种选择器）
                submit_selectors = [
                    "button[type='submit']",
                    "button:has-text('登录')",
                    "button:has-text('Login')",
                    "input[type='submit']",
                ]
                clicked = False
                for sel in submit_selectors:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        clicked = True
                        logging.info(f"点击登录按钮: {sel}")
                        break
                if not clicked:
                    raise Exception("未找到登录按钮")

                # 等待跳转到用户中心
                page.wait_for_url(f"{self.USER_URL}*", timeout=20000)
                logging.info("登录成功！")

                # 签到流程
                page.goto(self.USER_URL, wait_until="networkidle")
                # 查找签到按钮
                sign_selectors = [
                    "button:has-text('签到')",
                    "a:has-text('签到')",
                    "button:has-text('每日签到')",
                    "#checkin-btn",
                    ".checkin-btn",
                ]
                clicked_sign = False
                for sel in sign_selectors:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        clicked_sign = True
                        logging.info(f"点击签到按钮: {sel}")
                        break

                if not clicked_sign:
                    # 备用：直接 POST 接口
                    logging.warning("未找到签到按钮，尝试直接调用签到 API")
                    response = page.request.post(
                        self.SIGN_URL,
                        headers={"Referer": self.USER_URL}
                    )
                    result_text = response.text()
                else:
                    page.wait_for_timeout(3000)  # 等待结果展示
                    # 尝试获取结果消息
                    result_locators = [
                        ".alert", ".toast", ".message", "#checkin-result", ".swal2-content"
                    ]
                    result_text = ""
                    for loc in result_locators:
                        el = page.locator(loc)
                        if el.count() > 0:
                            result_text = el.first.inner_text()
                            break
                    if not result_text:
                        result_text = "签到完成，请登录查看结果"

                logging.info(f"签到结果: {result_text}")
                self._send_notification(
                    title=f"{self.masked_username} 签到结果",
                    content=json.dumps({"msg": result_text}, ensure_ascii=False)
                )

            except PlaywrightTimeoutError as e:
                error_msg = f"操作超时: {e}"
                logging.error(error_msg)
                # 保存失败时截图
                page.screenshot(path="timeout_error.png")
                logging.info("已保存截图 timeout_error.png")
                self._send_notification(title=f"{self.masked_username} 签到失败", content=error_msg)
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
    parser = argparse.ArgumentParser(description="V2Free 自动签到脚本 (Playwright 增强版)")
    parser.add_argument("--username", type=str, help="登录邮箱")
    parser.add_argument("--password", type=str, help="登录密码")
    args = parser.parse_args()

    username = os.environ.get("V2FREE_USERNAME") or args.username
    password = os.environ.get("V2FREE_PASSWORD") or args.password

    if not username or not password:
        logging.error("请通过环境变量或命令行参数提供账号密码")
        sys.exit(1)

    checker = V2FreeCheckIn(username, password)
    checker.run()

if __name__ == "__main__":
    main()
