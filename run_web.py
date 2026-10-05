"""Web 版启动入口。

用法：python run_web.py
服务监听 0.0.0.0:8000，局域网内手机/iPad/电脑均可访问 http://<主机IP>:8000

HTTPS（可选）：设置 ENGLISH_COACH_SSL_CERT / ENGLISH_COACH_SSL_KEY 指向证书
与私钥后以 https 启动。局域网部署建议配置（见 deploy/README.md 的 mkcert
章节）：浏览器仅在安全上下文（https 或 localhost）开放麦克风权限，纯
http://<局域网IP> 在手机/iPad 上无法录音。
"""
import os

import uvicorn

if __name__ == "__main__":
    cert = os.environ.get("ENGLISH_COACH_SSL_CERT", "").strip()
    key = os.environ.get("ENGLISH_COACH_SSL_KEY", "").strip()
    uvicorn.run(
        "src.server.web_server:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        ssl_certfile=cert or None,
        ssl_keyfile=key or None,
    )
