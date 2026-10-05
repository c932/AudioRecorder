"""预热模型：把 GOP 对齐模型与 Whisper 下载到 /hf-cache 挂载卷。

首次部署后运行一次（可选，此后容器重启直接命中缓存）：
    docker compose run --rm backend python deploy/prewarm_models.py
"""
import os
import sys

# 以脚本路径运行时 sys.path[0] 是 deploy/，补上仓库根目录才能 import src.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ENGLISH_COACH_HEADLESS", "1")

from src.server.deps import load_config


def main() -> None:
    cfg = load_config()

    gop_model = cfg.get("gop_model", "facebook/wav2vec2-lv-60-espeak-cv-ft")
    print(f"== 预热 GOP 对齐模型（{gop_model}，约 1.2GB）==")
    from src.core.gop.aligner import Wav2Vec2Aligner
    Wav2Vec2Aligner(model_name=gop_model).load()

    whisper_size = cfg.get("whisper_model_size", "medium")
    print(f"== 预热 Whisper（{whisper_size}，约 1.5GB）==")
    import whisper
    whisper.load_model(whisper_size)

    print("== 完成：模型已缓存到 /hf-cache 卷 ==")


if __name__ == "__main__":
    main()
