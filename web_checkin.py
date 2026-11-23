"""Use the ordinary check-in page once, stopping if the site requests verification."""
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error, sync_playwright

from checkin import CURRENT_SESSION_COOKIES, LEGACY_SESSION_COOKIES, get_cookies

SITE = "https://glados.cloud"
CHECKIN = SITE + "/console/checkin"
REWARD = re.compile(r"Checkin!\s*Got\s+(\d+(?:\.\d+)?)\s*Points?", re.I)
ALREADY = re.compile(r"today.s observation logged|checkin repeats|already checked in today", re.I)
VERIFICATION = re.compile(r"verify (?:that )?you are human|verify you are a human|verification failed|nothing was recorded|automated check.in detected|请验证您是真人", re.I)


def check_account(browser, cookie):
    fields = dict(item.strip().split("=", 1) for item in cookie.split(";") if "=" in item)
    names = next((pair for pair in (CURRENT_SESSION_COOKIES, LEGACY_SESSION_COOKIES)
                  if all(fields.get(name) for name in pair)), None)
    if not names:
        return False, "仓库登录凭据不完整"
    with browser.new_context() as context:
        context.add_cookies([{"name": name, "value": fields[name], "url": SITE + "/",
                              "secure": True, "httpOnly": True} for name in names])
        page = context.new_page()
        page.goto(CHECKIN, wait_until="domcontentloaded", timeout=45000)
        submitted = False
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            location = urlsplit(page.url)
            if location.hostname != "glados.cloud" or location.scheme != "https":
                return False, "官网发生跨站跳转，已停止"
            body = page.locator("body").inner_text(timeout=5000)
            if VERIFICATION.search(body) or page.locator('iframe[src*="challenges.cloudflare.com"]:visible').count():
                return False, "官网要求验证，当次签到未获确认"
            if location.path.startswith("/login") or "Get Code" in body:
                return False, "官网登录页要求重新登录"
            if ALREADY.search(body):
                return True, "官网确认今天已经签到"
            reward = REWARD.search(body)
            if reward:
                if submitted:
                    return True, f"官网返回签到奖励 +{reward.group(1)} 分"
                return True, "官网已显示今天的签到奖励"
            button = page.get_by_role("button", name="Checkin", exact=True)
            if (not submitted and location.path == "/console/checkin"
                    and page.get_by_role("heading", name="Points", exact=True).count()
                    and button.count() == 1 and button.is_enabled()):
                submitted = True
                button.click(timeout=4000)
            time.sleep(0.8)
        return False, "官网未确认签到结果" if submitted else "未看到可用的官网签到按钮"


def main():
    cookies = get_cookies()
    if not cookies:
        return 1
    all_ok = True
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        for number, cookie in enumerate(cookies, 1):
            try:
                ok, result = check_account(browser, cookie)
            except Error:
                ok, result = False, "浏览器访问未完成，当次签到未获确认"
            summary = f"账号 {number} · {result}"
            print(summary, flush=True)
            if os.environ.get("GITHUB_STEP_SUMMARY"):
                with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as report:
                    print(summary, file=report)
            all_ok = all_ok and ok
        browser.close()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
