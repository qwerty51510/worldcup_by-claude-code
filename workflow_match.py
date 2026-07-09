#!/usr/bin/env python3
"""
單場比賽完整工作流：
  1. 生成縮圖（1280x720）
  2. 剪輯 Shorts（60s 9:16）
  3. 上傳長影音 + 設定縮圖
  4. 上傳 Shorts
  5. 更新兩支影片描述，互相連結

用法：
  python3 workflow_match.py fra          # 法摩預測
  python3 workflow_match.py arg          # 阿根廷復盤
  python3 workflow_match.py fra --dry    # 只生成縮圖/Shorts，不上傳
"""
import os, sys, subprocess, pickle, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
import numpy as np

# ── 路徑 ──────────────────────────────────────────────
ROOT  = Path(__file__).parent
BROLL = ROOT / "output" / "broll"
OUT   = ROOT / "output" / "workflow_out"
OUT.mkdir(exist_ok=True)

SITE_URL = "https://qwerty51510.github.io/worldcup_by-claude-code/index.html"
CHANNEL_URL = "https://www.youtube.com/@球是圓的AI體育分析"

FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_LIGHT = "/System/Library/Fonts/STHeiti Light.ttc"

# ── 比賽設定 ──────────────────────────────────────────
MATCHES = {
    "fra": {
        # 長影音
        "longform_video": ROOT / "output/wc_fra_mar_longform/wc2026_FRA_MAR_longform_v1.mp4",
        "longform_title": "2022年的噩夢又來了？AI算出法國這次有幾%機率守住｜八強賽前分析",
        "longform_desc": """\
法國 vs 摩洛哥 | 2026 世界盃 八強 | 賽前 AI 深度分析

2022年摩洛哥打進四強，今天他們再次碰上法國。摩洛哥有辦法再創奇蹟嗎？

模型數據
- 法國 ELO：2005（全球第二）
- 摩洛哥 ELO：1762（差距 +243）
- 法國預期進球：1.82 | 摩洛哥：0.87
- 讓球線：法國 -0.5
- 法國勝率：60% | 平局：23% | 摩洛哥：17%
- 預測比分：1-0 法國

0:00 開場懸念
0:34 法國實力分析
2:10 摩洛哥防守反擊體系
3:50 讓球邏輯分析
5:20 關鍵變數
7:00 最終預測

{SHORTS_LINK}

即時預測看板（每場更新）：
https://qwerty51510.github.io/worldcup_by-claude-code/index.html

上一場 - 阿根廷 vs 埃及 完整復盤：
{PREV_VIDEO_LINK}

世界盃2026 法國 摩洛哥 Mbappe 哈基米 足球分析 WorldCup2026 AI足球
""",
        "longform_tags": ["世界盃2026","法國","摩洛哥","Mbappe","哈基米",
                          "足球分析","AI足球","WorldCup2026","France","Morocco","八強","讓球"],
        # Shorts
        "shorts_start": "3:25",   # S6 預測場景
        "shorts_title": "AI算出法國 vs 摩洛哥勝率｜2022惡夢重演？#Shorts #世界盃2026",
        "shorts_desc": """\
AI模型八強賽前分析 - 法國 60% 勝率，法國 -0.5 讓球
完整分析在頻道長影音！
{LONGFORM_LINK}
世界盃2026 法國 摩洛哥 AI足球 Shorts WorldCup2026
""",
        "shorts_tags": ["世界盃2026","法國","摩洛哥","AI足球","Shorts","WorldCup2026","八強"],
        # 縮圖設計
        "thumb_bg":     BROLL / "hakimi_action2.jpg",    # 全版背景
        "thumb_left":   BROLL / "mbappe_action1.jpg",    # 左側球員
        "thumb_right":  BROLL / "hakimi_action1.jpg",    # 右側球員
        "thumb_hook":   "2022惡夢重演？",
        "thumb_sub":    "AI 算出法國勝率 60%",
        "thumb_match":  "法國  VS  摩洛哥",
        "thumb_badge":  "八強 AI分析",
        "thumb_accent": "#FFD700",
    },
    "arg": {
        "longform_video": ROOT / "output/wc_arg_egy_longform/wc2026_ARG_EGY_longform_v1.mp4",
        "longform_title": "梅西點球被撲、0比2落後⋯最後23分鐘連進3球！AI賽前早就算到了",
        "longform_desc": """\
阿根廷 vs 埃及 | 2026 世界盃 16強 | 完整復盤 + AI 讓球分析

AI 模型賽前預測：埃及讓球 +1.5 有正期望值。
梅西點球被撲出，埃及一度 2-0 領先，最後 23 分鐘阿根廷連進 3 球逆轉。

模型數據
- 阿根廷預期進球：2.03 | 埃及：0.66
- 讓球線：埃及 +1.5
- 最終比分：阿根廷 3-2 埃及（贏差 1 球，未到 1.5）
- AH 結果：命中

0:00 開場懸念
0:34 賽前 AI 分析
1:50 埃及率先破門
2:40 梅西點球被撲
3:55 阿根廷 0-2 瀕臨出局
5:10 最後 23 分鐘大逆轉
7:20 讓球結果分析
9:30 戰術拆解

{SHORTS_LINK}

即時預測看板（每場更新）：
https://qwerty51510.github.io/worldcup_by-claude-code/index.html

世界盃2026 阿根廷 埃及 梅西 足球分析 WorldCup2026 AI足球
""",
        "longform_tags": ["世界盃2026","阿根廷","埃及","梅西","足球分析",
                          "AI足球","WorldCup2026","Argentina","Egypt","Messi","讓球","16強"],
        "shorts_start": "3:00",   # S6 逆轉場景
        "shorts_title": "0-2落後最後23分鐘連進3球！梅西的逆轉#Shorts #世界盃2026",
        "shorts_desc": """\
AI賽前預測命中！阿根廷 3-2 埃及，讓球埃及+1.5過線
完整復盤在頻道長影音！
{LONGFORM_LINK}
世界盃2026 阿根廷 埃及 梅西 AI足球 Shorts WorldCup2026
""",
        "shorts_tags": ["世界盃2026","阿根廷","埃及","梅西","AI足球","Shorts","WorldCup2026","16強"],
        "thumb_bg":     BROLL / "egypt_match_01.jpg",
        "thumb_left":   BROLL / "messi_2026.jpg",
        "thumb_right":  BROLL / "mostafa_zico.jpg",
        "thumb_hook":   "23分鐘連進3球！",
        "thumb_sub":    "AI 賽前早就算到了",
        "thumb_match":  "阿根廷  VS  埃及",
        "thumb_badge":  "16強 AI復盤",
        "thumb_accent": "#00FF88",
    },
}

# ═══════════════════════════════════════════════════════
#  1. 縮圖生成（1280×720）
# ═══════════════════════════════════════════════════════
TW, TH = 1280, 720

def make_thumbnail(cfg, out_path):
    """生成 YouTube 縮圖：背景暗化 + 左右球員漸層 + 大字文案"""
    # 背景
    bg = Image.open(cfg["thumb_bg"]).convert("RGB")
    iw, ih = bg.size
    r = max(TW / iw, TH / ih)
    bg = bg.resize((int(iw*r), int(ih*r)), Image.LANCZOS)
    x = (bg.width - TW) // 2
    y = (bg.height - TH) // 2
    bg = bg.crop((x, y, x+TW, y+TH))
    bg = ImageEnhance.Brightness(bg).enhance(0.30)   # 壓暗讓字清晰

    # 漸層遮罩工具
    def paste_player(player_path, side, w_pct=0.38):
        pw = int(TW * w_pct)
        ph = TH
        player = Image.open(player_path).convert("RGB")
        piw, pih = player.size
        sc = ph / pih
        player = player.resize((int(piw*sc), ph), Image.LANCZOS)
        if player.width > pw:
            if side == "left":
                player = player.crop((0, 0, pw, ph))
            else:
                player = player.crop((player.width-pw, 0, player.width, ph))
        else:
            player = player.resize((pw, ph), Image.LANCZOS)

        mask = Image.new("L", (pw, ph), 255)
        fade = int(pw * 0.6)
        arr = np.array(mask, dtype=np.float32)
        for xi in range(fade):
            a = int(200 * (xi / fade) ** 1.2)
            if side == "left":
                arr[:, pw-1-xi] = a
            else:
                arr[:, xi] = a
        mask = Image.fromarray(arr.astype(np.uint8))
        x_pos = 0 if side == "left" else TW - pw
        bg.paste(player, (x_pos, 0), mask)

    paste_player(cfg["thumb_left"],  "left",  0.38)
    paste_player(cfg["thumb_right"], "right", 0.36)

    # 中央暗色漸層帶（讓文字更易讀）
    overlay = Image.new("RGBA", (TW, TH), (0,0,0,0))
    draw_ov = ImageDraw.Draw(overlay)
    for xi in range(TW):
        dist = abs(xi - TW//2) / (TW//2)
        alpha = int(160 * (1 - dist**1.5))
        draw_ov.line([(xi, 0), (xi, TH)], fill=(0,0,0,alpha))
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")

    # 文字層
    layer = Image.new("RGBA", (TW, TH), (0,0,0,0))
    d = ImageDraw.Draw(layer)

    def t(text, x, y, size, color, anchor="mm", box_alpha=0):
        f = ImageFont.truetype(FONT_BOLD, size)
        if box_alpha > 0:
            bb = d.textbbox((x,y), text, font=f, anchor=anchor)
            pad = 12
            d.rounded_rectangle([bb[0]-pad, bb[1]-pad, bb[2]+pad, bb[3]+pad],
                                 radius=8, fill=(0,0,0,box_alpha))
        col = tuple(int(color.lstrip("#")[i:i+2], 16) for i in (0,2,4)) + (255,)
        d.text((x, y), text, font=f, fill=col, anchor=anchor)

    cx = TW // 2

    # Badge（上方）
    t(cfg["thumb_badge"], cx, 55,  32, "#FFFFFF", "mm", box_alpha=160)
    # 比賽標題
    t(cfg["thumb_match"], cx, 160, 48, "#AACCFF", "mm", box_alpha=0)
    # 主 hook（最大）
    t(cfg["thumb_hook"],  cx, 340, 98, cfg["thumb_accent"], "mm", box_alpha=0)
    # 副標
    t(cfg["thumb_sub"],   cx, 480, 44, "#FFFFFF", "mm", box_alpha=140)
    # 品牌
    t("球是圓的 AI體育分析", cx, 660, 30, "#888888", "mm", box_alpha=0)

    result = Image.alpha_composite(bg.convert("RGBA"), layer).convert("RGB")
    result.save(str(out_path), quality=95)
    print(f"  縮圖：{out_path}  ({Path(out_path).stat().st_size//1024} KB)")
    return out_path


# ═══════════════════════════════════════════════════════
#  2. Shorts 剪輯（60s，9:16 1080×1920）
# ═══════════════════════════════════════════════════════
def extract_shorts(cfg, out_path):
    """從長影音截取 60s，轉 9:16"""
    start = cfg["shorts_start"]   # "5:10" 格式
    src   = str(cfg["longform_video"])

    # 9:16 crop：從 1920x1080 中心裁 608x1080，再 scale 到 1080x1920
    vf = "crop=608:1080:(iw-608)/2:0,scale=1080:1920"

    subprocess.run([
        "ffmpeg", "-y", "-ss", start, "-i", src,
        "-t", "60",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(out_path)
    ], check=True, capture_output=True)
    print(f"  Shorts：{out_path}  ({Path(out_path).stat().st_size//1024} KB)")
    return out_path


# ═══════════════════════════════════════════════════════
#  3. YouTube 上傳 + 縮圖
# ═══════════════════════════════════════════════════════
SCOPES        = ["https://www.googleapis.com/auth/youtube"]
CLIENT_SECRET = str(ROOT / "client_secret.json")
TOKEN_FILE    = str(ROOT / "yt_channel_token.pickle")  # 需要 full scope

def get_credentials():
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    import urllib.parse
    from wsgiref.simple_server import make_server, WSGIRequestHandler

    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
    flow.redirect_uri = "http://127.0.0.1:8765"
    auth_url, _ = flow.authorization_url(prompt="consent")
    print("\n" + "="*60)
    print("請到無痕視窗完成授權：")
    print(auth_url)
    print("="*60 + "\n", flush=True)
    result = {}
    def app(env, sr):
        result["code"] = urllib.parse.parse_qs(env.get("QUERY_STRING","")).get("code",[None])[0]
        sr("200 OK",[("Content-Type","text/html")])
        return ["<h2>授權完成</h2>".encode()]
    class Silent(WSGIRequestHandler):
        def log_message(self, *a): pass
    httpd = make_server("127.0.0.1", 8765, app, handler_class=Silent)
    print("等待授權…", flush=True)
    httpd.handle_request()
    httpd.server_close()
    flow.fetch_token(code=result["code"])
    creds = flow.credentials
    with open(TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)
    return creds


def upload_video(yt, video_path, title, description, tags, is_short=False):
    from googleapiclient.http import MediaFileUpload
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "17",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    print(f"  上傳：{title[:30]}…")
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"    {int(status.progress()*100)}%", end="\r")
    vid_id = resp["id"]
    print(f"    完成 → https://www.youtube.com/watch?v={vid_id}")
    return vid_id


def set_thumbnail(yt, video_id, thumb_path):
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(thumb_path), mimetype="image/jpeg")
    yt.thumbnails().set(videoId=video_id, media_body=media).execute()
    print(f"  縮圖已套用 → {video_id}")


def update_description(yt, video_id, new_desc):
    # 先取現有 snippet
    res = yt.videos().list(part="snippet", id=video_id).execute()
    snippet = res["items"][0]["snippet"]
    snippet["description"] = new_desc
    yt.videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()
    print(f"  描述已更新 → {video_id}")


# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════
def main():
    key = sys.argv[1] if len(sys.argv) > 1 else None
    dry = "--dry" in sys.argv

    if key not in MATCHES:
        print("用法：python3 workflow_match.py arg|fra [--dry]")
        sys.exit(1)

    cfg = MATCHES[key]
    print(f"\n=== 工作流：{key.upper()} ===")

    # Step 1: 縮圖
    print("\n[1/4] 生成縮圖…")
    thumb_path = OUT / f"thumb_{key}.jpg"
    make_thumbnail(cfg, thumb_path)

    # Step 2: Shorts 剪輯
    print("\n[2/4] 剪輯 Shorts…")
    shorts_path = OUT / f"shorts_{key}.mp4"
    extract_shorts(cfg, shorts_path)

    if dry:
        print("\n--dry 模式，跳過上傳。")
        return

    # Step 3 & 4: 上傳
    print("\n[3/4] 上傳影片…")
    from googleapiclient.discovery import build
    creds = get_credentials()
    yt = build("youtube", "v3", credentials=creds)

    # 讀取上一支影片 ID（如果有）
    prev_video_url = ""
    results_dir = OUT
    for f in sorted(results_dir.glob("result_*.json"), reverse=True):
        if f.stem != f"result_{key}":
            prev = json.loads(f.read_text())
            prev_video_url = prev.get("longform_url", "")
            break

    # 長影音（描述先不含 Shorts 連結）
    lf_desc = cfg["longform_desc"].replace("{SHORTS_LINK}", "（Shorts 版本即將上傳）")
    lf_desc = lf_desc.replace("{PREV_VIDEO_LINK}", prev_video_url or "（敬請期待）")
    lf_id = upload_video(yt, cfg["longform_video"],
                         cfg["longform_title"], lf_desc, cfg["longform_tags"])
    set_thumbnail(yt, lf_id, thumb_path)

    # Shorts
    sh_desc = cfg["shorts_desc"].replace(
        "{LONGFORM_LINK}", f"https://www.youtube.com/watch?v={lf_id}")
    sh_id = upload_video(yt, shorts_path,
                         cfg["shorts_title"], sh_desc, cfg["shorts_tags"], is_short=True)

    # Step 5: 更新長影音描述，加入 Shorts 連結
    print("\n[4/4] 互連兩支影片…")
    lf_desc_final = cfg["longform_desc"].replace(
        "{SHORTS_LINK}",
        f"60 秒精華版（Shorts）：https://www.youtube.com/shorts/{sh_id}")
    lf_desc_final = lf_desc_final.replace(
        "{PREV_VIDEO_LINK}", prev_video_url or "（敬請期待）")
    update_description(yt, lf_id, lf_desc_final)

    print(f"""
=== 完成 ===
長影音：https://www.youtube.com/watch?v={lf_id}
Shorts ：https://www.youtube.com/shorts/{sh_id}
縮圖  ：{thumb_path}
""")

    # 存結果供後續使用
    result_file = OUT / f"result_{key}.json"
    result_file.write_text(json.dumps({
        "longform_id": lf_id,
        "shorts_id": sh_id,
        "longform_url": f"https://www.youtube.com/watch?v={lf_id}",
        "shorts_url": f"https://www.youtube.com/shorts/{sh_id}",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
