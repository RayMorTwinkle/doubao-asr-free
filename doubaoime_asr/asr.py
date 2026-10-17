from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from enum import Enum, auto
import json
from pathlib import Path
import time
from typing import AsyncIterator, Callable, List, Optional, Union
import uuid
from pydantic import BaseModel, Field
import websockets
from websockets import ClientConnection

from .config import ASRConfig, SessionConfig
from .audio import AudioEncoder
from .asr_pb2 import AsrRequest, AsrResponse as AsrResponsePb, FrameState

# PCM 音频数据的类型别名
AudioChunk = bytes


class ResponseType(Enum):
    """
    ASR 响应类型
    """
    TASK_STARTED = auto()
    SESSION_STARTED = auto()
    SESSION_FINISHED = auto()
    VAD_START = auto()
    INTERIM_RESULT = auto()
    FINAL_RESULT = auto()
    HEARTBEAT = auto()
    ERROR = auto()
    UNKNOWN = auto()


@dataclass
class ASRResponse:
    """
    ASR 响应
    """
    type: ResponseType
    text: str = ""
    is_final: bool = False
    vad_start: bool = False
    vad_finished: bool = False
    packet_number: int = -1
    error_msg: str = ""
    raw_json: Optional[dict] = None


class ASRError(Exception):
    """
    ASR 错误
    """
    def __init__(self, message: str, response: Optional[ASRResponse] = None) -> None:
        super().__init__(message)
        self.response = response


class _SessionState(BaseModel):
    """
    ASR 会话状态
    """
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    final_text: str = ""
    is_finished: bool = False
    error: Optional[ASRResponse] = None


class DoubaoASR:
    """
    豆包输入法 ASR 客户端
    """
    def __init__(self, config: Optional[ASRConfig] = None):
        self.config = config
        self._encoder = AudioEncoder(self.config)
    
    async def __aenter__(self) -> DoubaoASR:
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    async def transcribe(self, audio: Union[str, Path, bytes], *, realtime = False, on_interim: Callable[[str], None] = None) -> str:
        """
        非流式语音识别

        :param audio: 音频文件路径或 PCM 字节数据
        :param on_interim: 可选的中间结果回调
        :return: 最终识别文本
        """
        final_text = ""
        async for response in self.transcribe_stream(audio, realtime=realtime):
            if response.type == ResponseType.INTERIM_RESULT and on_interim:
                on_interim(response.text)
            elif response.type == ResponseType.FINAL_RESULT:
                final_text = response.text
            elif response.type == ResponseType.ERROR:
                raise ASRError(response.error_msg, response)
        return final_text
    
    async def transcribe_stream(self, audio: Union[str, Path, bytes], *, realtime: bool = False) -> AsyncIterator[ASRResponse]:
        """
        流式语音识别（完整音频）

        :param audio: 音频文件路径或 PCM 字节数据
        :param realtime: 是否按实时速度发送
        :return: ASR 响应流，包括中间结果和最终结果
        """
        if isinstance(audio, (str, Path)):
            pcm_data = self._encoder.convert_audio_to_pcm(
                audio, self.config.sample_rate, self.config.channels,
            )
        else:
            pcm_data = audio

        opus_frames = self._encoder.pcm_to_opus_frames(pcm_data)
        state = _SessionState()

        try:
            async with websockets.connect(
                self.config.ws_url,
                additional_headers=self.config.headers,
                open_timeout=self.config.connect_timeout,
            ) as ws:
                # 初始化会话
                async for resp in self._initialize_session(ws, state):
                    yield resp

                # 响应队列
                response_queue: asyncio.Queue[Optional[ASRResponse]] = asyncio.Queue()

                # 启动发送和接收任务
                send_task = asyncio.create_task(
                    self._send_audio(ws, opus_frames, state, realtime)
                )
                recv_task = asyncio.create_task(
                    self._receive_responses(ws, state, response_queue)
                )

                try:
                    # 从队列中获取服务器响应
                    while True:
                        try:
                            resp = await asyncio.wait_for(
                                response_queue.get(),
                                timeout=self.config.recv_timeout,
                            )
                            if resp is None: # 结束标记
                                break

                            # 心跳包仅用于重置超时，不转发给用户
                            if resp.type == ResponseType.HEARTBEAT:
                                continue

                            yield resp
                            if resp.type == ResponseType.ERROR:
                                break

                        except asyncio.TimeoutError:
                            break

                    await send_task
                finally:
                    send_task.cancel()
                    recv_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await send_task
                    with contextlib.suppress(asyncio.CancelledError):
                        await recv_task

        except websockets.exceptions.WebSocketException as e:
            raise ASRError(f"WebSocket 错误: {e}") from e

    async def transcribe_realtime(
        self,
        audio_source: AsyncIterator[AudioChunk],
    ) -> AsyncIterator[ASRResponse]:
        """
        实时流式语音识别（支持麦克风等持续音频源）

        :param audio_source: PCM 音频数据的异步迭代器
            - 每个 chunk 应为 16-bit PCM 数据
            - 采样率和声道数应与 config 中配置一致
            - 迭代器结束时会自动发送 FinishSession
        :return: ASR 响应流
        """
        state = _SessionState()

        try:
            async with websockets.connect(
                self.config.ws_url,
                additional_headers=self.config.headers,
                open_timeout=self.config.connect_timeout,
            ) as ws:
                # 初始化会话
                async for resp in self._initialize_session(ws, state):
                    yield resp

                # 响应队列
                response_queue: asyncio.Queue[Optional[ASRResponse]] = asyncio.Queue()

                # 启动发送和接收任务
                send_task = asyncio.create_task(
                    self._send_audio_realtime(ws, audio_source, state)
                )
                recv_task = asyncio.create_task(
                    self._receive_responses(ws, state, response_queue)
                )

                try:
                    # 实时模式不使用超时，依靠 WebSocket 层检测断开
                    while True:
                        resp = await response_queue.get()
                        if resp is None:
                            break

                        if resp.type == ResponseType.HEARTBEAT:
                            continue

                        yield resp
                        if resp.type == ResponseType.ERROR:
                            break

                    await send_task
                finally:
                    send_task.cancel()
                    recv_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await send_task
                    with contextlib.suppress(asyncio.CancelledError):
                        await recv_task

        except websockets.exceptions.WebSocketException as e:
            raise ASRError(f"WebSocket 错误: {e}") from e

    async def _send_audio_realtime(
        self,
        ws: ClientConnection,
        audio_source: AsyncIterator[AudioChunk],
        state: _SessionState,
    ):
        """
        从异步迭代器读取 PCM 数据并实时发送
        """
        timestamp_ms = int(time.time() * 1000)
        frame_index = 0
        pcm_buffer = b""

        samples_per_frame = (
            self.config.sample_rate * self.config.frame_duration_ms // 1000
        )
        bytes_per_frame = samples_per_frame * 2  # 16-bit

        async for chunk in audio_source:
            if state.is_finished:
                break

            pcm_buffer += chunk

            # 当缓冲区有足够数据时，编码并发送
            while len(pcm_buffer) >= bytes_per_frame:
                pcm_frame = pcm_buffer[:bytes_per_frame]
                pcm_buffer = pcm_buffer[bytes_per_frame:]

                # 编码为 Opus
                opus_frame = self._encoder.encoder.encode(pcm_frame, samples_per_frame)

                # 确定帧状态（实时模式下不知道最后一帧，使用 FIRST/MIDDLE）
                if frame_index == 0:
                    frame_state = FrameState.FRAME_STATE_FIRST
                else:
                    frame_state = FrameState.FRAME_STATE_MIDDLE

                msg = _build_asr_request(
                    opus_frame,
                    state.request_id,
                    frame_state,
                    timestamp_ms + frame_index * self.config.frame_duration_ms,
                )
                await ws.send(msg)
                frame_index += 1

        # 迭代器结束，处理剩余数据
        if pcm_buffer and not state.is_finished:
            # 补零到完整帧
            if len(pcm_buffer) < bytes_per_frame:
                pcm_buffer += b"\x00" * (bytes_per_frame - len(pcm_buffer))

            opus_frame = self._encoder.encoder.encode(pcm_buffer, samples_per_frame)

            msg = _build_asr_request(
                opus_frame,
                state.request_id,
                FrameState.FRAME_STATE_LAST,
                timestamp_ms + frame_index * self.config.frame_duration_ms,
            )
            await ws.send(msg)
        elif frame_index > 0 and not state.is_finished:
            # 没有剩余数据，但需要发送一个 LAST 帧标记
            # 发送一个空的 LAST 帧（静音）
            silent_frame = b"\x00" * bytes_per_frame
            opus_frame = self._encoder.encoder.encode(silent_frame, samples_per_frame)

            msg = _build_asr_request(
                opus_frame,
                state.request_id,
                FrameState.FRAME_STATE_LAST,
                timestamp_ms + frame_index * self.config.frame_duration_ms,
            )
            await ws.send(msg)

        # FinishSession
        if not state.is_finished:
            await ws.send(_build_finish_session(state.request_id, self.config.get_token()))
    
    async def _initialize_session(self, ws: ClientConnection, state: _SessionState) -> AsyncIterator[ASRResponse]:
        """
        初始化 ASR 会话
        """
        token = self.config.get_token()

        # StartTask
        await ws.send(_build_start_task(state.request_id, token))
        resp = await ws.recv()
        parsed = _parse_response(resp)
        if parsed.type == ResponseType.ERROR:
            raise ASRError(f'StartTask 失败：{parsed.error_msg}', parsed)
        yield parsed

        # StartSession
        await ws.send(
            _build_start_session(state.request_id, token, self.config.session_config())
        )
        resp = await ws.recv()
        parsed = _parse_response(resp)
        if parsed.type == ResponseType.ERROR:
            raise ASRError(f'StartSession 失败：{parsed.error_msg}', parsed)
        yield parsed

    async def _send_audio(
        self,
        ws: ClientConnection,
        opus_frames: List[bytes],
        state: _SessionState,
        realtime: bool,
    ):
        """
        发送音频帧
        """
        timestamp_ms = int(time.time() * 1000)
        frame_interval = self.config.frame_duration_ms / 1000.0

        for i, opus_frame in enumerate(opus_frames):
            if state.is_finished:
                break

            if i == 0:
                frame_state = FrameState.FRAME_STATE_FIRST
            elif i == len(opus_frames) - 1:
                frame_state = FrameState.FRAME_STATE_LAST
            else:
                frame_state = FrameState.FRAME_STATE_MIDDLE
            
            msg = _build_asr_request(
                opus_frame,
                state.request_id,
                frame_state,
                timestamp_ms + i * self.config.frame_duration_ms,
            )
            await ws.send(msg)

            if realtime:
                await asyncio.sleep(frame_interval)
        
        # FinishSession
        await ws.send(_build_finish_session(state.request_id, self.config.get_token()))
    
    async def _receive_responses(
        self,
        ws: ClientConnection,
        state: _SessionState,
        queue: asyncio.Queue[Optional[ASRResponse]],
    ):
        """
        接受响应并放入队列
        """
        try:
            while not state.is_finished:
                response = await ws.recv()
                resp = _parse_response(response)

                if resp.type == ResponseType.ERROR:
                    state.error = resp
                    state.is_finished = True
                    await queue.put(resp)
                    break
                elif resp.type == ResponseType.HEARTBEAT:
                    # 心跳包也放入队列，用于重置超时计时器
                    await queue.put(resp)
                elif resp.type == ResponseType.SESSION_FINISHED:
                    state.is_finished = True
                    await queue.put(resp)
                    break
                elif resp.type == ResponseType.FINAL_RESULT:
                    state.final_text = resp.text
                    await queue.put(resp)
                else:
                    await queue.put(resp)

        except websockets.exceptions.ConnectionClosed:
            state.is_finished = True
        finally:
            # 结束信号
            await queue.put(None)


    
def _build_start_task(request_id: str, token: str) -> bytes:
    """构建 StartTask 消息 pb 数据"""
    request = AsrRequest()
    request.token = token
    request.service_name = "ASR"
    request.method_name = "StartTask"
    request.request_id = request_id
    return request.SerializeToString()


def _build_start_session(request_id: str, token: str, config: SessionConfig) -> bytes:
    """构建 StartSession 消息 pb 数据"""
    request = AsrRequest()
    request.token = token
    request.service_name = "ASR"
    request.method_name = "StartSession"
    request.request_id = request_id
    request.payload = config.model_dump_json()
    return request.SerializeToString()


def _build_finish_session(request_id: str, token: str) -> bytes:
    """构建 FinishSession 消息 pb 数据"""
    request = AsrRequest()
    request.token = token
    request.service_name = "ASR"
    request.method_name = "FinishSession"
    request.request_id = request_id
    return request.SerializeToString()


def _build_asr_request(
    audio_data: bytes,
    request_id: str,
    frame_state: FrameState,
    timestamp_ms: int,
) -> bytes:
    request = AsrRequest()
    metadata = json.dumps({"extra": {}, "timestamp_ms": timestamp_ms})

    request.service_name = "ASR"
    request.method_name = "TaskRequest"
    request.payload = metadata
    request.audio_data = audio_data
    request.request_id = request_id
    request.frame_state = frame_state
    return request.SerializeToString()



def _parse_response(data: bytes) -> ASRResponse:
    """解析 ASR 响应 (使用 protobuf)"""
    pb = AsrResponsePb()
    pb.ParseFromString(data)

    message_type = pb.message_type
    result_json = pb.result_json  # 字段 7: 识别结果 JSON
    status_message = pb.status_message  # 字段 6: 状态消息

    # 根据 message_type 判断响应类型
    if message_type == "TaskStarted":
        return ASRResponse(type=ResponseType.TASK_STARTED)

    if message_type == "SessionStarted":
        return ASRResponse(type=ResponseType.SESSION_STARTED)

    if message_type == "SessionFinished":
        return ASRResponse(type=ResponseType.SESSION_FINISHED)

    if message_type in ("TaskFailed", "SessionFailed"):
        return ASRResponse(type=ResponseType.ERROR, error_msg=status_message)

    # 识别结果在 result_json 字段（字段 7）
    if not result_json:
        return ASRResponse(type=ResponseType.UNKNOWN)

    try:
        json_data = json.loads(result_json)
    except json.JSONDecodeError:
        return ASRResponse(type=ResponseType.UNKNOWN)

    results = json_data.get("results")
    extra = json_data.get("extra", {})

    # 无 results，可能是心跳包
    if results is None:
        return ASRResponse(
            type=ResponseType.HEARTBEAT,
            packet_number=extra.get("packet_number", -1),
            raw_json=json_data,
        )

    # VAD 开始
    if extra.get("vad_start"):
        return ASRResponse(type=ResponseType.VAD_START, vad_start=True, raw_json=json_data)

    # 解析识别结果
    text = ""
    is_interim = True
    vad_finished = False
    nonstream_result = False

    for r in results:
        if r.get("text"):
            text = r.get("text")
        if r.get("is_interim") is False:
            is_interim = False
        if r.get("is_vad_finished"):
            vad_finished = True
        if r.get("extra", {}).get("nonstream_result"):
            nonstream_result = True

    # 最终结果
    if nonstream_result or (not is_interim and vad_finished):
        return ASRResponse(
            type=ResponseType.FINAL_RESULT,
            text=text,
            is_final=True,
            vad_finished=vad_finished,
            raw_json=json_data,
        )

    # 中间结果
    return ASRResponse(
        type=ResponseType.INTERIM_RESULT,
        text=text,
        is_final=False,
        raw_json=json_data,
    )


# =============
# 便捷函数
# =============


async def transcribe(
    audio: str | Path | bytes,
    *,
    config: ASRConfig | None = None,
    on_interim: Callable[[str], None] | None = None,
    realtime: bool = False,
) -> str:
    """
    便捷函数：非流式语音识别

    Args:
        audio: 音频文件路径或 PCM 字节数据
        config: ASR 配置（可选）
        on_interim: 中间结果回调（可选）
        realtime: 是否模拟实时语音输入
            - True: 按音频实际时长发送，每帧间插入延迟，模拟实时的语音输入
            - False（默认）: 尽快发送所有帧，会更快拿到结果（不知道会不会被风控）

    Returns:
        最终识别文本
    """
    async with DoubaoASR(config) as asr:
        return await asr.transcribe(audio, on_interim=on_interim, realtime=realtime)


async def transcribe_stream(
    audio: str | Path | bytes,
    *,
    config: ASRConfig | None = None,
    realtime: bool = False,
) -> AsyncIterator[ASRResponse]:
    """
    便捷函数：流式语音识别（完整音频）

    Args:
        audio: 音频文件路径或 PCM 字节数据
        config: ASR 配置（可选）
        realtime: 是否模拟实时语音输入
            - True: 按音频实际时长发送，每帧间插入延迟，模拟实时的语音输入
            - False（默认）: 尽快发送所有帧，会更快拿到结果（不知道会不会被风控）

    Yields:
        ASRResponse 对象
    """
    async with DoubaoASR(config) as asr:
        async for resp in asr.transcribe_stream(audio, realtime=realtime):
            yield resp


async def transcribe_realtime(
    audio_source: AsyncIterator[AudioChunk],
    *,
    config: ASRConfig | None = None,
) -> AsyncIterator[ASRResponse]:
    """
    便捷函数：实时流式语音识别（支持麦克风等持续音频源）

    Args:
        audio_source: PCM 音频数据的异步迭代器
            - 每个 chunk 应为 16-bit PCM 数据
            - 采样率和声道数应与 config 中配置一致
        config: ASR 配置（可选）

    Yields:
        ASRResponse 对象
    """
    async with DoubaoASR(config) as asr:
        async for resp in asr.transcribe_realtime(audio_source):
            yield resp
