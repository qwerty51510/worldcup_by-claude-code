#!/usr/bin/env python3
"""Upload channel banner to YouTube via API."""
import os, pickle, warnings
warnings.filterwarnings("ignore")
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from wsgiref.simple_server import make_server, WSGIRequestHandler
import urllib.parse

SCOPES        = ["https://www.googleapis.com/auth/youtube"]
CLIENT_SECRET = os.path.join(os.path.dirname(__file__), "client_secret.json")
TOKEN_FILE    = os.path.join(os.path.dirname(__file__), "yt_channel_token.pickle")
BANNER_FILE   = os.path.join(os.path.dirname(__file__),
                              "output/channel_art/banner.png")

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

    result = {}
    def app(environ, start_response):
        qs = urllib.parse.parse_qs(environ.get("QUERY_STRING",""))
        result["code"] = qs.get("code",[None])[0]
        start_response("200 OK",[("Content-Type","text/html")])
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

def upload_banner(creds):
    yt = build("youtube", "v3", credentials=creds)
    print("上傳 banner 圖片…")
    media = MediaFileUpload(BANNER_FILE, mimetype="image/png", resumable=False)
    resp  = yt.channelBanners().insert(body={}, media_body=media).execute()
    url   = resp["url"]
    print(f"圖片已上傳：{url}")

    print("取得頻道 ID…")
    ch = yt.channels().list(part="id", mine=True).execute()
    channel_id = ch["items"][0]["id"]
    print(f"頻道 ID：{channel_id}")

    print("取得現有頻道設定…")
    ch_info = yt.channels().list(
        part="brandingSettings", id=channel_id
    ).execute()
    branding = ch_info["items"][0].get("brandingSettings", {})

    # Merge banner URL into existing settings
    branding.setdefault("image", {})["bannerExternalUrl"] = url

    print("套用到頻道…")
    yt.channels().update(
        part="brandingSettings",
        body={"id": channel_id, "brandingSettings": branding}
    ).execute()
    print("封面更新完成！")

if __name__ == "__main__":
    creds = get_credentials()
    upload_banner(creds)
