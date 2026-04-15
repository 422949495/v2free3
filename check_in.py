# coding=UTF-8

import os
import sys
import logging
import requests
from requests.utils import quote
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ---------- 配置日志 ----------
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

class V2FreeCheckIn:
    LOGIN_URL = "https://w2.v2free.top/auth/login"
    USER_URL = "https://w2.v2free.top/user"

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.masked_username = self._mask_email(username)

    @staticmethod
    def _mask_email(email: str) -> str:
        """邮箱脱敏显示"""
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
        with sync_playwright() as p:
            # 启动浏览器
            browser = p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']
            )
            # 创建浏览器上下文，模拟中国大陆环境
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="zh-CN",        # 设置浏览器语言为简体中文[reference:4]
                timezone_id="Asia/Shanghai" # 设置时区为上海[reference:5]
            )
            page = context.new_page()

            try:
                # 1. 访问登录页
                logging.info(f"正在访问登录页: {self.LOGIN_URL}")
                page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

                # 2. 尝试处理 "Select Language" 弹窗
                try:
                    # 等待语言选择器出现，如果在3秒内出现则处理
                    lang_selector = page.wait_for_selector("text=Select Language", timeout=3000)
                    if lang_selector:
                        logging.info("检测到语言选择弹窗，正在切换为简体中文...")
                        lang_selector.click()
                        # 等待“简体中文”选项出现并点击
                        page.wait_for_selector("text=简体中文", timeout=3000).click()
                        logging.info("已成功切换为简体中文")
                        page.wait_for_timeout(1000) # 等待页面刷新
                except PlaywrightTimeoutError:
                    # 未检测到语言弹窗，正常流程
                    logging.info("未检测到语言选择弹窗，继续执行")
                except Exception as e:
                    logging.warning(f"处理语言弹窗时发生异常: {e}")

                # 3. 等待并填写登录表单
                page.wait_for_selector("input[name='Email']", timeout=10000)
                page.wait_for_selector("input[name='Password']", timeout=10000)

                logging.info(f"正在登录 {self.masked_username} ...")
                page.fill("input[name='Email']", self.username)
                page.fill("input[name='Password']", self.password)

                # 4. 点击登录按钮
                page.click("button:has-text('登录')")
                logging.info("已点击登录按钮，等待页面跳转...")
                page.screenshot(path="after_login_click.png") # 点击后截图，用于调试

                # 5. 等待登录成功后的跳转
                try:
                    # 等待跳转到用户中心页面
                    page.wait_for_url(f"{self.USER_URL}*", timeout=30000)
                    logging.info("登录成功，已跳转至用户中心！")
                except PlaywrightTimeoutError:
                    current_url = page.url
                    # 检查是否已经位于用户中心（可能URL已变化但匹配失败）
                    if self.USER_URL in current_url:
                        logging.info(f"当前已在用户中心: {current_url}")
                    else:
                        # 登录失败，保存截图并抛出异常
                        page.screenshot(path="login_failed.png")
                        # 检查页面是否有错误提示
                        error_el = page.query_selector(".alert-danger, .text-danger, .error")
                        error_msg = error_el.inner_text() if error_el else "登录后未能跳转到用户中心"
                        raise Exception(f"登录失败: {error_msg}。当前URL: {current_url}")

                # 6. 进入用户中心页面
                page.goto(self.USER_URL, wait_until="networkidle")
                logging.info("正在查找签到按钮...")

                # 7. 点击签到按钮
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
                        page.screenshot(path="after_sign_click.png") # 签到后截图
                        break

                if not clicked_sign:
                    logging.warning("未找到签到按钮，可能已签到或页面结构变更。")
                    result_text = "未找到签到按钮"
                else:
                    page.wait_for_timeout(3000) # 等待签到结果提示
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
                    content=result_text
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
    # 从环境变量读取账号密码
    username = os.environ.get("V2FREE_USERNAME")
    password = os.environ.get("V2FREE_PASSWORD")

    if not username or not password:
        logging.error("请设置环境变量 V2FREE_USERNAME 和 V2FREE_PASSWORD")
        sys.exit(1)

    checker = V2FreeCheckIn(username, password)
    checker.run()

if __name__ == "__main__":
    main()
