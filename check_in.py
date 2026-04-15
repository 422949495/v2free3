# coding=UTF-8

import os
import sys
import json
import logging
import argparse
import requests
from requests.utils import quote
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

class V2FreeAutoSign:
    LOGIN_URL = "https://w2.v2free.top/auth/login"
    USER_URL = "https://w2.v2free.top/user"

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.masked_username = self._mask_email(username)

    @staticmethod
    def _mask_email(email: str) -> str:
        at = email.rfind('@')
        if at == -1:
            return email
        return email[0] + '******' + email[at:at+2] + '***'

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
            page = context.new_page()

            try:
                # ---------- 1. 登录 ----------
                logging.info(f"正在访问登录页: {self.LOGIN_URL}")
                page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

                # 等待输入框
                page.wait_for_selector("input[name='Email']", timeout=10000)
                page.wait_for_selector("input[name='Password']", timeout=10000)

                logging.info(f"正在登录 {self.masked_username} ...")
                page.fill("input[name='Email']", self.username)
                page.fill("input[name='Password']", self.password)

                # 点击登录并等待跳转到用户中心
                page.click("button:has-text('登录')")
                page.wait_for_url(f"{self.USER_URL}*", timeout=30000)
                logging.info("✅ 登录成功，已进入用户中心")

                # ---------- 2. 签到 ----------
                page.goto(self.USER_URL, wait_until="networkidle")
                logging.info("正在查找签到按钮...")

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
                    # 可能今日已签到
                    page.screenshot(path="no_sign_button.png")
                    result_text = "未找到签到按钮，可能今日已签到"
                else:
                    # 等待签到结果（Turnstile 验证会自动处理，通常 3~5 秒）
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
                            result_text = "操作已完成，请手动确认"

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", type=str, help="登录邮箱")
    parser.add_argument("--password", type=str, help="登录密码")
    args = parser.parse_args()

    username = os.environ.get("V2FREE_USERNAME") or args.username
    password = os.environ.get("V2FREE_PASSWORD") or args.password

    if not username or not password:
        logging.error("请通过环境变量或参数提供账号密码")
        sys.exit(1)

    signer = V2FreeAutoSign(username, password)
    signer.run()

if __name__ == "__main__":
    main()
