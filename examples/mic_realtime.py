"""
麦克风实时语音识别示例

依赖: pip install sounddevice numpy
"""
import asyncio

from doubaoime_asr.asr import transcribe_realtime, ResponseType
from doubaoime_asr.config import ASRConfig


async def mic_audio_generator(
    sample_rate: int = 16000,
    channels: int = 1,
    frame_duration_ms: int = 20,
):
    """
    麦克风音频生成器

    使用 sounddevice 从麦克风读取音频数据，通过回调模式避免阻塞事件循环
    """
    import sounddevice as sd
    import numpy as np

    # 每帧样本数
    samples_per_frame = sample_rate * frame_duration_ms // 1000

    # 使用 asyncio.Queue 在回调和异步生成器之间传递数据
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def audio_callback(indata, frames, time_info, status):
        """sounddevice 回调函数（在单独线程中运行）"""
        if status:
            print(f"[Mic] 状态: {status}")
        # 将数据放入队列（线程安全）
        loop.call_soon_threadsafe(queue.put_nowait, indata.tobytes())

    print(f"[Mic] 开始录音 (按 Ctrl+C 停止)...")
    print(f"[Mic] 采样率: {sample_rate}Hz, 声道: {channels}, 帧时长: {frame_duration_ms}ms")

    with sd.InputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype=np.int16,
        blocksize=samples_per_frame,
        callback=audio_callback,
    ):
        while True:
            # 异步等待音频数据
            data = await queue.get()
            yield data


async def main():
    config = ASRConfig(credential_path="./credentials.json")

    print("=" * 50)
    print("豆包输入法实时语音识别")
    print("=" * 50)
    print()

    try:
        async for response in transcribe_realtime(
            mic_audio_generator(
                sample_rate=config.sample_rate,
                channels=config.channels,
                frame_duration_ms=config.frame_duration_ms,
            ),
            config=config,
        ):
            if response.type == ResponseType.TASK_STARTED:
                print("[系统] 任务已启动")
            elif response.type == ResponseType.SESSION_STARTED:
                print("[系统] 会话已启动，开始说话...")
                print()
            elif response.type == ResponseType.VAD_START:
                print("[VAD] 检测到语音开始")
            elif response.type == ResponseType.INTERIM_RESULT:
                # 使用回车覆盖显示中间结果
                print(f"\r[识别中] {response.text}", end="", flush=True)
            elif response.type == ResponseType.FINAL_RESULT:
                # 清除中间结果并显示最终结果
                print(f"\r[最终] {response.text}          ")
            elif response.type == ResponseType.SESSION_FINISHED:
                print("\n[系统] 会话结束")
            elif response.type == ResponseType.ERROR:
                print(f"\n[错误] {response.error_msg}")

    except KeyboardInterrupt:
        print("\n\n[系统] 用户中断，停止录音")


if __name__ == "__main__":
    asyncio.run(main())
