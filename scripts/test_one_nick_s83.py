import asyncio
import json
import random
import re
import ssl
import struct
import sys
import time
import urllib.parse
import urllib.request
import websockets

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REROLL_GIFTCODES = [
    "45THANTUONG", "DUONGTIEN", "NGOKHONG", "NATRA",
    "DAT100KDKT", "DKT50K", "DKT30K", "THANCAN555", "YCAN666",
    "TOP1STORE", "HACTAYDU888", "TAYDUKI", "CHUONGCAM",
    "HTDCC999", "HOICHIEUTROIMUA", "THUANPHAM", "VAN97",
    "HOANGDZ", "NHANCAN111", "NHICAN222", "TICAN333",
    "THIETCAN444", "DKT5K", "DKT10K", "DKT20K",
    "CCC2026", "NGOCKEN", "DOITAC666"
]


def _pkt_str(s):
    b = s.encode("utf-8")
    return struct.pack(">H", len(b)) + b


def _pkt_msg(msg_id, payload=b""):
    return struct.pack(">HH", len(payload), msg_id) + payload


def get_public_ip():
    try:
        return urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode("utf-8").strip()
    except Exception as e:
        return f"unknown ({e})"


def pop_account():
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        "https://152-69-209-107.sslip.io/api/accounts/pop",
        headers={"User-Agent": "HacTayDu-GH-Test/1.0"},
    )
    with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok") or not data.get("account"):
        raise RuntimeError(f"Hub empty: {data}")
    return data["account"]


def fetch_fresh_authkey(account_id, access_token="r"):
    ctx = ssl._create_unverified_context()
    url = (
        f"https://funtap-xy.xinliugame.net/game/igame.php?"
        f"funtap_id={account_id}&access_token={urllib.parse.quote(str(access_token))}"
        f"&app_key=9893d7e4df3c9d0f6e20eb672c07a95f&plt=ios&platform=funtap&appid=ios"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
        },
    )
    with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    m_ts = re.search(r"GLOBAL_TIMESTAMP\s*=\s*['\"]?(\d+)['\"]?", html)
    m_ak = re.search(r"GLOBAL_AUTHKEY\s*=\s*['\"]([a-fA-F0-9]+)['\"]", html)
    if not m_ts or not m_ak:
        raise RuntimeError("Could not parse GLOBAL_AUTHKEY from igame.php")
    return {"timestamp": int(m_ts.group(1)), "authKey": m_ak.group(1)}


def _parse_hero_gt(buf, off):
    if off + 4 > len(buf):
        return None, len(buf)
    hero_id = struct.unpack_from(">i", buf, off)[0]
    off += 4
    if off + 2 > len(buf):
        return None, len(buf)
    u_len = struct.unpack_from(">H", buf, off)[0]
    off += 2 + u_len
    if off + 2 > len(buf):
        return None, len(buf)
    n_len = struct.unpack_from(">H", buf, off)[0]
    off += 2
    name_cn = buf[off:off + n_len].decode("utf-8", errors="replace")
    off += n_len
    if off + 2 > len(buf):
        return None, len(buf)
    title_len = struct.unpack_from(">H", buf, off)[0]
    off += 2 + title_len
    if off + 23 > len(buf):
        return None, len(buf)
    star = buf[off + 20]
    off += 23
    return {"id": hero_id, "name": name_cn, "star": star}, off


def parse_heroes(resp):
    _, mid = struct.unpack(">HH", resp[:4])
    out = []
    if mid == 38 and len(resp) >= 6:
        cnt = struct.unpack_from(">H", resp, 4)[0]
        off = 6
        for _ in range(cnt):
            h, off = _parse_hero_gt(resp, off)
            if h:
                out.append(h)
    elif mid == 21 and len(resp) > 4:
        h, _ = _parse_hero_gt(resp, 4)
        if h:
            out.append(h)
    return out


async def main():
    gh_ip = get_public_ip()
    print(f"[*] GitHub Actions Public IP: {gh_ip}", flush=True)

    acc = pop_account()
    username = acc["username"]
    password = acc["password"]
    funtap_id = str(acc["accountId"])
    access_tok = acc.get("accessToken") or "r"
    sid = 610083
    ws_url = "wss://wss-funtap-xy.xinliugame.net:9109/"
    print(f"[*] Account: {username} | Pass: {password} | FuntapID: {funtap_id}", flush=True)
    print(f"[*] Target Server: [S83 Mới Nhất] Hỏa Diệm Sơn-S3 (sid={sid}, {ws_url})", flush=True)

    ak_info = fetch_fresh_authkey(funtap_id, access_tok)
    json_datas = json.dumps({"gamePlatform": "funtap", "appid": "ios", "pf": "ios_funtap", "phoneSystem": 2})
    login_payload = bytearray()
    login_payload.extend(_pkt_str(f"{sid}-{funtap_id}"))
    login_payload.extend(struct.pack(">i", int(ak_info["timestamp"])))
    login_payload.extend(_pkt_str(ak_info["authKey"]))
    login_payload.extend(_pkt_str("vn"))
    login_payload.extend(_pkt_str("VN"))
    login_payload.extend(_pkt_str(gh_ip))
    login_payload.extend(_pkt_str(json_datas))
    login_payload.extend(_pkt_str(""))
    login_pkt = _pkt_msg(56, login_payload)

    ctx = ssl._create_unverified_context()
    heroes_5star = []
    seen_bag_list = False
    cdk_ev = asyncio.Event()
    mail_count = 0

    t_total = time.time()
    async with websockets.connect(ws_url, ssl=ctx, open_timeout=12, ping_interval=None, ping_timeout=None) as ws:
        async def reader():
            nonlocal seen_bag_list, mail_count
            async for resp in ws:
                if not isinstance(resp, bytes) or len(resp) < 4:
                    continue
                sz, mid = struct.unpack(">HH", resp[:4])
                if mid == 144:
                    cdk_ev.set()
                elif mid == 10 and sz >= 10:
                    msg = resp[14:].decode("utf-8", errors="replace")
                    if msg.startswith("已达到领取上限"):
                        cdk_ev.set()
                elif mid == 69 and sz > 3:
                    mail_count = struct.unpack(">H", resp[4:6])[0]
                elif mid == 38:
                    if not seen_bag_list:
                        seen_bag_list = True
                        for h in parse_heroes(resp):
                            if h["star"] >= 5:
                                heroes_5star.append(h["name"])
                elif mid == 21:
                    for h in parse_heroes(resp):
                        if h["star"] >= 5:
                            heroes_5star.append(h["name"])

        rtask = asyncio.create_task(reader())
        await ws.send(login_pkt)
        await asyncio.sleep(0.35)
        clean_role_name = re.sub(r"[^a-zA-Z0-9]", "", username)[:14]
        await ws.send(_pkt_msg(122, _pkt_str(clean_role_name) + b"\x00"))
        await asyncio.sleep(0.25)
        if not seen_bag_list:
            await ws.send(_pkt_msg(122, _pkt_str(f"{clean_role_name[:10]}{random.randint(10, 99)}") + b"\x00"))
            await asyncio.sleep(0.25)
        await ws.send(_pkt_msg(91, struct.pack(">i", 1)))
        await ws.send(_pkt_msg(598, struct.pack(">i", 1)))
        await asyncio.sleep(0.45)

        confirmed = []
        failed = []
        for idx, code in enumerate(REROLL_GIFTCODES, 1):
            cdk_ev.clear()
            t0 = time.time()
            await ws.send(_pkt_msg(143, _pkt_str(code)))
            try:
                await asyncio.wait_for(cdk_ev.wait(), timeout=3.8)
                confirmed.append(code)
                print(f"  [{idx:02d}/28] OK  {code:<16} ({time.time()-t0:.2f}s)", flush=True)
            except asyncio.TimeoutError:
                failed.append(code)
                print(f"  [{idx:02d}/28] ERR {code:<16} (TIMEOUT 3.8s)", flush=True)
            await asyncio.sleep(0.55)

        await asyncio.sleep(1.20)
        await ws.send(_pkt_msg(64, b"\x01"))
        await ws.send(_pkt_msg(64, b"\x02"))
        await ws.send(_pkt_msg(61))
        await asyncio.sleep(0.45)
        await ws.send(_pkt_msg(61))
        await asyncio.sleep(0.35)

        for item_id, qty in [(703, 2), (703, 1), (704, 2), (704, 1), (1012, 1)]:
            await ws.send(_pkt_msg(87, struct.pack(">ii", item_id, qty)))
            await asyncio.sleep(0.18)
        await asyncio.sleep(0.35)
        await ws.send(_pkt_msg(61))
        await asyncio.sleep(0.35)

        await ws.send(_pkt_msg(1320, b"\x01"))
        await asyncio.sleep(0.10)
        await ws.send(_pkt_msg(213, struct.pack(">bbb", 1, 1, 1)))
        await asyncio.sleep(0.40)
        for _ in range(6):
            await ws.send(_pkt_msg(213, struct.pack(">bbb", 1, 2, 1)))
            await asyncio.sleep(0.45)
        for _ in range(7):
            await ws.send(_pkt_msg(213, struct.pack(">bbb", 1, 1, 1)))
            await asyncio.sleep(0.44)

        await ws.send(_pkt_msg(213, struct.pack(">bbb", 4, 2, 1)))
        await asyncio.sleep(0.45)
        for _ in range(4):
            await ws.send(_pkt_msg(213, struct.pack(">bbb", 4, 1, 1)))
            await asyncio.sleep(0.44)
        await asyncio.sleep(0.50)
        rtask.cancel()

    print("\n" + "=" * 75)
    print(f"RESULT ON S83 FROM GITHUB ACTIONS IP ({gh_ip}):")
    print(f"  - Account       : {username} | Pass: {password} | UID: {funtap_id}")
    print(f"  - Total Time    : {time.time() - t_total:.1f}s")
    print(f"  - Codes Claimed : {len(confirmed)}/28 (Mails in box: {mail_count})")
    if failed:
        print(f"  - Failed Codes  : {failed}")
    print(f"  - Total 5★      : {len(heroes_5star)}★ ({heroes_5star})")
    print("=" * 75, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
