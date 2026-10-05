"""Web 版启动入口。

用法：python run_web.py
服务监听 0.0.0.0:8000，局域网内手机/iPad/电脑均可访问 http://<主机IP>:8000
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.server.web_server:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
