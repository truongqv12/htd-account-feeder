"""Worker script executed inside GitHub Actions runners to generate fresh accounts.
Runs on Azure/GitHub runner with unique IP, registers accounts via headless Playwright,
and pushes them to the central Account Hub.
"""

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.request
import urllib.error

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", write_through=True)

from playwright.sync_api import sync_playwright

VIETNAMESE_NAMES = [
    "Nguyen Van An", "Tran Quoc Tuan", "Le Hoang Long", "Pham Duc Anh",
    "Hoang Minh Tri", "Dang Van Lam", "Vu Quang Huy", "Bui Tien Dung",
    "Doan Van Hau", "Nguyen Quang Hai", "Phan Van Duc", "Nguyen Cong Phuong",
    "Nguyen Tien Linh", "Que Ngoc Hai", "Do Hung Dung", "Nguyen Tuan Anh"
]

DEVICES = [
    "Pixel 6", "Pixel 7", "Galaxy S22", "Galaxy S23", "Galaxy S24",
    "Redmi Note 12", "Xiaomi 13", "Oppo Reno 8", "Vivo V27"
]

def register_one_account(page, worker_id, seq):
    prefix = "tdha" if worker_id <= 10 else "htdvipz"
    rnd_num = random.randint(10000, 99999)
    username = f"{prefix}{rnd_num}"
    password = f"Pw@{random.randint(100000, 999999)}"
    device = random.choice(DEVICES)
    fullname = random.choice(VIETNAMESE_NAMES)
    phone_prefix = random.choice(["097", "098", "096", "035", "036", "037", "038", "086", "091", "094"])
    phone = f"{phone_prefix}{random.randint(1000000, 9999999)}"
    birth_year = random.randint(1995, 2004)
    birth_month = f"{random.randint(1, 12):02d}"
    birth_day = f"{random.randint(1, 28):02d}"
    birthday = f"{birth_year}-{birth_month}-{birth_day}"

    target_url = (
        f"https://core.sdkmain.com/v1/apps/2a456b78cf5122cd9278ef24b4d7bfb9/9.9.9.5/register/phone"
        f"?sdk_version=6.1.2&device_network=wifi&device_os=Android%2012&device_name={device.replace(' ', '%20')}"
    )

    t0 = time.time()
    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=12000)
        page.wait_for_selector("#username", timeout=10000)
    except Exception as e:
        print(f"[{worker_id}#{seq}] Goto/wait error: {e}")
        return None

    submit_js = f"""
    (() => {{
        try {{
            const u = document.getElementById("username");
            const f = document.getElementById("fullname");
            const b = document.getElementById("birthday");
            const p = document.getElementById("phone");
            const pwd = document.getElementById("password");
            const form = document.querySelector('form');
            
            if (!u || !form) return {{ok: false, error: 'Form elements missing'}};
            
            u.value = {json.dumps(username)};
            f.value = {json.dumps(fullname)};
            b.value = {json.dumps(birthday)};
            p.value = {json.dumps(phone)};
            pwd.value = {json.dumps(password)};
            
            for (let el of [u, f, b, p, pwd]) {{
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
            }}
            
            if (typeof grecaptcha !== 'undefined' && grecaptcha.enterprise) {{
                const siteKey = '6Lc7WFYsAAAAAIZ1uFlJpFgSlbcFFdGYHXgaVcVU';
                grecaptcha.enterprise.ready(function() {{
                    grecaptcha.enterprise.execute(siteKey, {{action: 'submit'}}).then(function(token) {{
                        const rInput = document.getElementById('g-recaptcha-response');
                        if (rInput) rInput.value = token;
                        form.submit();
                    }});
                }});
            }} else {{
                form.submit();
            }}
            return {{ok: true}};
        }} catch(e) {{
            return {{ok: false, error: String(e)}};
        }}
    }})()
    """

    res = page.evaluate(submit_js)
    if not res.get("ok"):
        print(f"[{worker_id}#{seq}] Submit error: {res.get('error')}")

    content = ""
    for _ in range(12):
        try:
            content = page.content()
            if "loginSuccess" in content:
                break
            time.sleep(0.2)
        except Exception:
            time.sleep(0.15)

    registered_info = None
    if "loginSuccess" in content:
        m = re.search(r"appSDKexecute\('loginSuccess',\s*(\{.*?\})\);", content)
        if m:
            try:
                registered_info = json.loads(m.group(1))
            except Exception:
                pass

    dur = time.time() - t0
    if registered_info:
        data_block = registered_info.get("data", {})
        account_block = data_block.get("account", {}) if isinstance(data_block, dict) else {}
        acc_id = str(account_block.get("account_id") or data_block.get("id") or "")
        fun_id = str(data_block.get("id") or "")
        token = str(registered_info.get("access_token") or "r")

        acc_obj = {
            "username": username,
            "password": password,
            "accountId": acc_id,
            "accessToken": token,
            "funId": fun_id,
            "source": f"gh_worker_{worker_id}"
        }
        print(f"[{worker_id}#{seq}] ✅ Created {username} (ID: {acc_id}) in {dur:.2f}s")
        return acc_obj
    else:
        print(f"[{worker_id}#{seq}] ❌ Registration failed in {dur:.2f}s")
        return None

def push_accounts_to_hub(hub_url, secret, accounts):
    if not accounts:
        return
    req_data = json.dumps({"accounts": accounts}).encode("utf-8")
    req = urllib.request.Request(
        hub_url,
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Secret": secret,
            "User-Agent": "GitHub-Actions-Feeder/1.0"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            print(f"🚀 [Hub Push] Successfully pushed {len(accounts)} accounts! Hub reply: {body}")
    except Exception as e:
        print(f"❌ [Hub Push Error] Failed to push to {hub_url}: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", type=int, default=1)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--hub-url", default=os.getenv("HUB_URL", "https://152-69-209-107.sslip.io/api/accounts/push"))
    parser.add_argument("--secret", default=os.getenv("HUB_SECRET", "d57be08c4bbbc9c7feda86285611ee41fc8016d4f1bf4a1a7a60502d123b0ab3"))
    parser.add_argument("--pace", type=float, default=2.5)
    args = parser.parse_args()

    print(f"=== Starting GitHub Reg Worker #{args.worker_id} (Target: {args.count} accounts) ===")
    created_accounts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 414, "height": 896},
            locale="vi-VN",
        )
        page = context.new_page()
        page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,otf}", lambda route: route.abort())

        consec_fails = 0
        for seq in range(1, args.count + 1):
            try:
                acc = register_one_account(page, args.worker_id, seq)
                if acc:
                    consec_fails = 0
                    created_accounts.append(acc)
                    # Stream micro-batches of 3 accounts directly into Hub so queue never waits
                    if len(created_accounts) >= 3:
                        push_accounts_to_hub(args.hub_url, args.secret, created_accounts)
                        created_accounts.clear()
                else:
                    consec_fails += 1
                    if consec_fails >= 3:
                        print(f"[{args.worker_id}] ⚠️ IP reached Funtap limit (3 consecutive fails at #{seq}), exiting early to rotate fresh Azure IP!")
                        break
            except Exception as e:
                print(f"[{args.worker_id}#{seq}] Loop exception: {e}")
                consec_fails += 1
                if consec_fails >= 3:
                    break
            if seq < args.count:
                time.sleep(args.pace)

        browser.close()

    print(f"=== Worker #{args.worker_id} Finished ===")
    if created_accounts:
        push_accounts_to_hub(args.hub_url, args.secret, created_accounts)

if __name__ == "__main__":
    main()
