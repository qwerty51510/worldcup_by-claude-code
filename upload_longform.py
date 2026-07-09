#!/usr/bin/env python3
"""上傳長影音到 YouTube。用法：python3 upload_longform.py arg | fra"""
import os, pickle, sys
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES        = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET = os.path.join(os.path.dirname(__file__), "client_secret.json")
TOKEN_FILE    = os.path.join(os.path.dirname(__file__), "yt_token.pickle")

VIDEOS = {
    "arg": {
        "file": "output/wc_arg_egy_longform/wc2026_ARG_EGY_longform_v1.mp4",
        "title": "梅西點球被撲、0比2落後⋯最後23分鐘連進3球！AI賽前早就算到了",
        "description": """\
阿根廷 vs 埃及 | 2026 世界盃 16強 | 完整復盤 + AI 讓球分析

AI 模型賽前預測：埃及讓球 +1.5 有正期望值。
梅西點球被撲出，埃及一度 2-0 領先，最後 23 分鐘阿根廷連進 3 球逆轉。

模型數據
- 阿根廷預期進球：2.03
- 埃及預期進球：0.66
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

世界盃2026 阿根廷 埃及 梅西 足球分析 WorldCup2026 AI足球
""",
        "tags": ["世界盃2026", "阿根廷", "埃及", "梅西", "足球分析",
                 "AI足球", "WorldCup2026", "Argentina", "Egypt", "Messi",
                 "讓球", "亞洲讓球", "16強"],
    },
    "fra": {
        "file": "output/wc_fra_mar_longform/wc2026_FRA_MAR_longform_v1.mp4",
        "title": "2022年的噩夢又來了？AI算出法國這次有幾%機率守住｜八強賽前分析",
        "description": """\
法國 vs 摩洛哥 | 2026 世界盃 八強 | 賽前 AI 深度分析

2022年摩洛哥打進四強，今天他們再次碰上法國。摩洛哥有辦法再創奇蹟嗎？

模型數據
- 法國 ELO：2005（全球第二）
- 摩洛哥 ELO：1762（差距 +243）
- 法國預期進球：1.82
- 摩洛哥預期進球：0.87
- 讓球線：法國 -0.5
- 法國勝率：60% | 平局：23% | 摩洛哥：17%
- 預測比分：1-0 法國

0:00 開場懸念
0:34 法國實力分析
2:10 摩洛哥防守反擊體系
3:50 讓球邏輯分析
5:20 關鍵變數
7:00 最終預測

世界盃2026 法國 摩洛哥 Mbappe 哈基米 足球分析 WorldCup2026 AI足球
""",
        "tags": ["世界盃2026", "法國", "摩洛哥", "Mbappe", "哈基米", "足球分析",
                 "AI足球", "WorldCup2026", "France", "Morocco", "八強",
                 "讓球", "亞洲讓球"],
    },
}


def get_credentials():
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
    print("請複製以下網址到【無痕視窗】完成授權：")
    print("="*60)
    print(auth_url)
    print("="*60 + "\n", flush=True)

    from wsgiref.simple_server import make_server, WSGIRequestHandler
    import urllib.parse

    result = {}
    def app(environ, start_response):
        qs = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        result["code"] = qs.get("code", [None])[0]
        start_response("200 OK", [("Content-Type", "text/html")])
        return ["<h2>授權完成，可以關閉這個視窗了</h2>".encode("utf-8")]

    class Silent(WSGIRequestHandler):
        def log_message(self, *a): pass

    httpd = make_server("127.0.0.1", 8765, app, handler_class=Silent)
    print("等待授權中…", flush=True)
    httpd.handle_request()
    httpd.server_close()
    flow.fetch_token(code=result["code"])
    creds = flow.credentials
    with open(TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)
    return creds


def upload(creds, key):
    meta = VIDEOS[key]
    base = os.path.dirname(__file__)
    video_path = os.path.join(base, meta["file"])

    if not os.path.exists(video_path):
        print(f"找不到影片：{video_path}")
        sys.exit(1)

    yt = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title":       meta["title"],
            "description": meta["description"],
            "tags":        meta["tags"],
            "categoryId":  "17",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    req  = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    print(f"上傳中：{meta['title']}")
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  {int(status.progress() * 100)}%")
    vid_id = resp["id"]
    print(f"\n上傳完成！")
    print(f"https://www.youtube.com/watch?v={vid_id}")
    return vid_id


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else None
    if key not in VIDEOS:
        print("用法：python3 upload_longform.py arg | fra")
        sys.exit(1)
    creds = get_credentials()
    upload(creds, key)
