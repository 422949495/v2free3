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

                # 2. 切换语言为简体中文
                # 寻找包含 "Select Language" 文本的元素并点击
                try:
                    logging.info("尝试切换语言为简体中文...")
                    # 等待语言选择器出现
                    lang_selector = page.locator("text=Select Language").first
                    lang_selector.wait_for(state="visible", timeout=5000)
                    lang_selector.click()
                    # 等待下拉菜单出现并点击简体中文
                    chinese_option = page.locator("text=简体中文").first
                    chinese_option.wait_for(state="visible", timeout=5000)
                    chinese_option.click()
                    # 等待页面刷新（语言切换后页面可能重新加载）
                    page.wait_for_load_state("networkidle")
                    logging.info("已成功切换语言为简体中文")
                except PlaywrightTimeoutError:
                    logging.warning("未找到语言切换器或已经为中文，继续执行")
                except Exception as e:
                    logging.warning(f"语言切换失败，但可尝试继续: {e}")

                # 3. 等待表单元素（中文界面下字段名可能不同）
                # 多尝试几个可能的选择器
                email_selectors = [
                    "input[name='Email']",
                    "input[name='email']",
                    "input[type='email']",
                    "#email"
                ]
                pass_selectors = [
                    "input[name='Password']",
                    "input[name='passwd']",
                    "input[type='password']",
                    "#password"
                ]
                email_input = None
                for sel in email_selectors:
                    if page.locator(sel).count() > 0:
                        email_input = sel
                        break
                if not email_input:
                    raise Exception("找不到邮箱输入框")

                pass_input = None
                for sel in pass_selectors:
                    if page.locator(sel).count() > 0:
                        pass_input = sel
                        break
                if not pass_input:
                    raise Exception("找不到密码输入框")

                logging.info(f"正在登录 {self.masked_username} ...")
                page.fill(email_input, self.username)
                page.fill(pass_input, self.password)

                # 4. 点击登录并等待导航
                # 查找登录按钮（中文界面下可能是“登录”）
                submit_btn = page.locator("button:has-text('登录')").first
                if submit_btn.count() == 0:
                    submit_btn = page.locator("button:has-text('Login')").first
                if submit_btn.count() == 0:
                    submit_btn = page.locator("button[type='submit']").first

                if submit_btn.count() == 0:
                    raise Exception("找不到登录按钮")

                # 使用 expect_navigation 精确等待跳转
                with page.expect_navigation(wait_until="networkidle", timeout=30000):
                    submit_btn.click()
                logging.info("登录请求已提交，页面发生跳转")

                # 5. 检查是否登录成功
                current_url = page.url
                if self.USER_URL not in current_url:
                    # 检查错误信息
                    error_text = ""
                    error_elements = page.locator(".alert-danger, .text-danger, .error, .invalid-feedback")
                    if error_elements.count() > 0:
                        error_text = error_elements.first.inner_text()
                    else:
                        body = page.locator("body").inner_text()
                        if "账号或密码错误" in body:
                            error_text = "账号或密码错误"
                        elif "验证码" in body:
                            error_text = "需要输入验证码"
                        else:
                            error_text = "未知错误，未跳转至用户中心"
                    raise Exception(f"登录失败: {error_text}")

                logging.info("登录成功，已进入用户中心！")

                # 6. 签到
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
