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
                # 1. 访问登录页面，并等待网络空闲
                logging.info(f"正在访问登录页: {self.LOGIN_URL}")
                page.goto(self.LOGIN_URL, wait_until="networkidle", timeout=60000)
                
                # 2. 等待登录表单加载完成
                page.wait_for_selector("input[name='Email']", timeout=10000)
                page.wait_for_selector("input[name='Password']", timeout=10000)
                
                # 3. 输入账号和密码
                logging.info(f"正在登录 {self.masked_username} ...")
                page.fill("input[name='Email']", self.username)
                page.fill("input[name='Password']", self.password)
                
                # 4. 点击登录按钮
                page.click("button:has-text('登录')")
                logging.info("已点击登录按钮，等待页面跳转...")
                
                # 5. 等待登录成功后的跳转
                try:
                    # 等待跳转到用户中心页面，增加超时时间到30秒
                    page.wait_for_url(f"{self.USER_URL}*", timeout=30000)
                    logging.info("登录成功，已跳转至用户中心！")
                except PlaywrightTimeoutError:
                    # 如果超时，检查当前URL是否是用户中心，可能已经跳转了但URL匹配失败
                    current_url = page.url
                    if self.USER_URL in current_url:
                        logging.info(f"当前已在用户中心: {current_url}")
                    else:
                        # 如果不在用户中心，可能是登录失败，保存截图并退出
                        page.screenshot(path="login_failed.png")
                        raise Exception(f"登录后未能跳转到用户中心，当前URL: {current_url}")

                # 6. 确保在用户中心页面
                page.goto(self.USER_URL, wait_until="networkidle")
                
                # 7. 签到
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
                    logging.warning("未找到签到按钮，尝试直接调用签到 API")
                    response = page.request.post(
                        self.SIGN_URL,
                        headers={"Referer": self.USER_URL}
                    )
                    result_text = response.text()
                else:
                    page.wait_for_timeout(3000)
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
