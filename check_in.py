# coding=UTF-8

import os
import sys
import json
import logging
import argparse
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
                # 1. 访问登录页
                logging.info(f"正在访问登录页: {self.LOGIN_URL}")
                page.goto(self.LOGIN_URL, wait_until="networkidle", timeout=60000)

                # 2. 尝试选择简体中文（如果存在语言切换器）
                try:
                    # 等待页面可能存在的语言下拉或按钮
                    lang_switcher = page.locator("text=Select Language").first
                    if lang_switcher.count() > 0:
                        lang_switcher.click()
                        # 点击后等待中文选项出现并点击
                        page.locator("text=简体中文").first.click(timeout=3000)
                        logging.info("已切换语言为简体中文")
                        page.wait_for_timeout(1000)  # 等待页面刷新
                except Exception:
                    pass  # 忽略语言切换失败，继续登录

                # 3. 等待表单元素
                page.wait_for_selector("input[name='Email']", timeout=10000)
                page.wait_for_selector("input[name='Password']", timeout=10000)

                logging.info(f"正在登录 {self.masked_username} ...")
                page.fill("input[name='Email']", self.username)
                page.fill("input[name='Password']", self.password)

                # 4. 点击登录并等待导航（表单提交后的跳转）
                # 使用 expect_navigation 来精确捕获 POST 后的页面跳转
                with page.expect_navigation(wait_until="networkidle", timeout=30000):
                    page.click("button:has-text('登录')")
                logging.info("登录请求已提交，页面发生跳转")

                # 5. 检查当前 URL 是否为用户中心
                current_url = page.url
                if self.USER_URL not in current_url:
                    # 未跳转到用户中心，可能登录失败，检查错误信息
                    error_selectors = [
                        ".alert-danger", ".text-danger", ".error", ".invalid-feedback"
                    ]
                    error_msg = ""
                    for sel in error_selectors:
                        el = page.locator(sel)
                        if el.count() > 0:
                            error_msg = el.first.inner_text()
                            break
                    if not error_msg:
                        # 尝试获取整个页面文本片段
                        body_text = page.locator("body").inner_text()
                        if "账号或密码错误" in body_text:
                            error_msg = "账号或密码错误"
                        elif "验证码" in body_text:
                            error_msg = "需要输入验证码"
                        else:
                            error_msg = "登录失败，未跳转至用户中心"
                    raise Exception(f"登录失败: {error_msg}")

                logging.info("登录成功，已进入用户中心！")

                # 6. 确保在用户中心页面并签到
                page.goto(self.USER_URL, wait_until="networkidle")

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
