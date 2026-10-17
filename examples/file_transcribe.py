"""
音频文件语音识别示例

演示 transcribe 和 transcribe_stream 两个函数的用法
"""
import asyncio
import requests

from doubaoime_asr import transcribe, transcribe_stream, ASRConfig, ResponseType


async def demo_transcribe(audio_data: bytes, config: ASRConfig):
    """
    非流式识别 (transcribe)

    直接返回最终识别结果
    """
    print("=" * 50)
    print("非流式识别 (transcribe)")
    print("=" * 50)

    # 简单用法：直接获取结果
    result = await transcribe(audio_data, config=config)
    print(f"识别结果: {result}")
    print()

    # 带中间结果回调
    print("带中间结果回调:")

    def on_interim(text: str):
        print(f"  [中间] {text}")

    result = await transcribe(audio_data, config=config, on_interim=on_interim)
    print(f"  [最终] {result}")
    print()


async def demo_transcribe_stream(audio_data: bytes, config: ASRConfig):
    """
    流式识别 (transcribe_stream)

    返回 ASRResponse 流，可以获取中间结果、VAD 事件等详细信息
    """
    print("=" * 50)
    print("流式识别 (transcribe_stream)")
    print("=" * 50)

    async for response in transcribe_stream(audio_data, config=config, realtime=False):
        match response.type:
            case ResponseType.TASK_STARTED:
                print("[系统] 任务已启动")
            case ResponseType.SESSION_STARTED:
                print("[系统] 会话已启动")
            case ResponseType.VAD_START:
                print("[VAD] 检测到语音开始")
            case ResponseType.INTERIM_RESULT:
                print(f"[中间] {response.text}")
            case ResponseType.FINAL_RESULT:
                print(f"[最终] {response.text}")
            case ResponseType.SESSION_FINISHED:
                print("[系统] 会话结束")
            case ResponseType.ERROR:
                print(f"[错误] {response.error_msg}")


def get_audio_data() -> bytes:
    """
    随便从 Github 上找的一个带有中文语音的音频文件
    """
    audio_url = 'https://github.com/liangstein/Chinese-speech-to-text/raw/refs/heads/master/1.wav'
    audio_data = requests.get(audio_url).content
    return audio_data


async def main():
    # 配置
    config = ASRConfig(credential_path="./credentials.json")

    audio_data = get_audio_data()

    await demo_transcribe(audio_data, config)
    await demo_transcribe_stream(audio_data, config)


if __name__ == "__main__":
    asyncio.run(main())
