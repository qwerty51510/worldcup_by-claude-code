#!/usr/bin/env python3
"""Upload a video to YouTube with OAuth (installed app flow)."""
import os, pickle, sys
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES           = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET    = os.path.join(os.path.dirname(__file__), "client_secret.json")
TOKEN_FILE       = os.path.join(os.path.dirname(__file__), "yt_token.pickle")
VIDEO_FILE       = os.path.join(os.path.dirname(__file__),
                                "output/wc_short_v5/wc2026_FRA_MAR_v5.mp4")

TITLE = "法國 vs 摩洛哥 世界盃2026 AI模型分析 #Shorts"
DESCRIPTION = """\
🤖 AI模型分析 法國 vs 摩洛哥
📊 ELO差距 +243，法國勝率 59%
⚽ 讓球建議：法國 -0.5
📈 近4場 AH 命中 4/4

模型每場世界盃重要賽事自動分析，訂閱不漏任何比賽！

#世界盃2026 #法國 #摩洛哥 #足球分析 #Shorts #WorldCup2026
"""
TAGS = ["世界盃2026", "法國", "摩洛哥", "足球分析", "AI足球", "Shorts",
        "WorldCup2026", "France", "Morocco", "football"]


def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
        flow.redirect_uri = "http://127.0.0.1:8765"
        auth_url, _ = flow.authorization_url(prompt="consent")
        print("\n" + "="*60)
        print("請複製以下網址，貼到【無痕視窗】完成授權：")
        print("="*60)
        print(auth_url)
        print("="*60 + "\n", flush=True)
        # Start local server waiting for callback
        from wsgiref.simple_server import make_server, WSGIRequestHandler
        import urllib.parse, threading

        result = {}

        def app(environ, start_response):
            qs = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
            result["code"] = qs.get("code", [None])[0]
            start_response("200 OK", [("Content-Type", "text/html")])
            return ["<h2>授權完成，可以關閉這個視窗了</h2>".encode("utf-8")]

        class Silent(WSGIRequestHandler):
            def log_message(self, *a): pass

        httpd = make_server("127.0.0.1", 8765, app, handler_class=Silent)
        print("等待授權中（在無痕視窗完成登入後會自動繼續）…", flush=True)
        httpd.handle_request()
        httpd.server_close()
        flow.fetch_token(code=result["code"])
        creds = flow.credentials
    with open(TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)
    return creds


def upload(creds):
    yt = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title":       TITLE,
            "description": DESCRIPTION,
            "tags":        TAGS,
            "categoryId":  "17",   # Sports
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(VIDEO_FILE, chunksize=-1, resumable=True,
                            mimetype="video/mp4")
    req  = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    print("上傳中…")
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  {int(status.progress() * 100)}%")
    vid_id = resp["id"]
    print(f"\n上傳完成！")
    print(f"https://www.youtube.com/shorts/{vid_id}")
    return vid_id


if __name__ == "__main__":
    if not os.path.exists(VIDEO_FILE):
        print(f"找不到影片：{VIDEO_FILE}"); sys.exit(1)
    creds = get_credentials()
    upload(creds)
