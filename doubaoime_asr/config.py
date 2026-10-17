from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Optional, Union
from pydantic import BaseModel

from .constants import WEBSOCKET_URL, USER_AGENT, AID
from .device import DeviceCredentials, register_device, get_asr_token


class _AudioInfo(BaseModel):
    channel: int
    format: str
    sample_rate: int


class _SessionExtraConfig(BaseModel):
    app_name: str
    cell_compress_rate: int
    did: str
    enable_asr_threepass: bool
    enable_asr_twopass: bool
    input_mode: str


class SessionConfig(BaseModel):
    """
    ASR 任务开始前需要初始化 Session 的配置
    """
    audio_info: _AudioInfo
    enable_punctuation: bool
    enable_speech_rejection: bool
    extra: _SessionExtraConfig


@dataclass
class ASRConfig:
    """
    ASR 配置

    如果不提供 device_id 和 token，将自动注册设备并获取 token。

    示例:
        # 自动获取凭据（首次使用时会注册设备，不持久化）
        config = ASRConfig()

        # 使用已有凭据
        config = ASRConfig(device_id="1234567890123456", token="MyToken123")

        # 使用凭据文件（推荐，首次注册后自动缓存）
        config = ASRConfig(credential_path="~/.config/doubao-asr/credentials.json")

        # 凭据文件 + 覆盖部分参数
        config = ASRConfig(
            credential_path="~/.config/doubao-asr/credentials.json",
            token="NewToken",  # 覆盖文件中的 token
        )
    """
    url: str = WEBSOCKET_URL
    aid: str = AID
    user_agent: str = USER_AGENT

    device_id: Optional[str] = None # 空则自动获取
    token: Optional[str] = None     # 空则自动获取
    credential_path: Union[str, Path, None] = None
    """
    凭据文件路径
    """

    # 这些都是客户端给的默认值，挺通用的。其实我也没尝试过改了服务器会不会认
    # 音频配置
    sample_rate: int = 16000
    channels: int = 1
    frame_duration_ms: int = 20

    # 会话配置
    enable_punctuation: bool = True
    enable_speech_rejection: bool = False
    enable_asr_twopass: bool = True
    enable_asr_threepass: bool = True
    # 这里是输入法当前作用在哪个应用上
    # 可能服务器会根据当前所使用的程序调整不同的语音识别策略？？
    # 这里用 Chrome 浏览器，算是比较通用的了吧？
    app_name: str = "com.android.chrome"

    # 连接配置
    connect_timeout: float = 10.0
    recv_timeout: float = 10.0

    # 内部状态
    _credentials: Optional[DeviceCredentials] = field(default=None, repr=None)
    _initialized: bool = field(default=False, repr=False)

    def _load_credentials_from_file(self) -> Optional[DeviceCredentials]:
        """
        从缓存文件中加载凭据信息
        """
        if self.credential_path is None:
            return None

        path = Path(self.credential_path).expanduser()
        if not path.exists():
            return None
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.loads(f.read())
                return DeviceCredentials(**data)

        except (json.JSONDecodeError, OSError):
            return None
    
    def _save_credentials_to_file(self, creds: DeviceCredentials):
        """
        保存凭据至缓存文件
        """
        if self.credential_path is None:
            return
        
        path = Path(self.credential_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(creds.model_dump(), f, indent=2, ensure_ascii=False)
    
    def ensure_credentials(self):
        """
        确保凭据已初始化

        优先级：
        1. 直接传入的 device_id/token 参数（最高优先级）
        2. credential_path 文件中的值
        3. 自动注册获取（最低优先级）

        如果指定了 credential_path 且文件不存在，会注册设备并保存到文件。
        """
        if self._initialized:
            return
        
        # 保存直接通过参数传入的凭据，用于进行覆盖
        user_device_id = self.device_id
        user_token = self.token

        # 尝试从文件中加载凭据
        file_creds = self._load_credentials_from_file()
        if file_creds:
            self._credentials = file_creds
            # 使用文件中的值作为默认
            if self.device_id is None:
                self.device_id = file_creds.device_id
            if self.token is None:
                self.token = file_creds.token
        
        # 如果 device_id 仍为 None, 则注册设备
        need_save = False
        if self.device_id is None:
            self._credentials = register_device()
            self.device_id = self._credentials.device_id
            need_save = True
        
        # 如果 token 仍为 None, 则获取 token
        if self.token is None:
            cdid = self._credentials.cdid if self._credentials else None
            self.token = get_asr_token(self.device_id, cdid)
        
        # 如果指定了 credential_path 且有新注册的凭据，则保存至文件
        if self.credential_path and need_save and self._credentials:
            self._credentials.token = self.token
            self._save_credentials_to_file(self._credentials)
        
        # 覆盖用户传入的参数
        if user_device_id is not None:
            self.device_id = user_device_id
        
        if user_token is not None:
            self.token = user_token

        self._initialized = True
    
    @property
    def ws_url(self) -> str:
        self.ensure_credentials()
        return f'{self.url}?aid={self.aid}&device_id={self.device_id}'
    
    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "proto-version": "v2",
            "x-custom-keepalive": "true"
        }

    def session_config(self) -> SessionConfig:
        self.ensure_credentials()
        audio_info = _AudioInfo(
            channel=self.channels,
            format="speech_opus",
            sample_rate=self.sample_rate,
        )
        extra = _SessionExtraConfig(
            app_name=self.app_name,
            cell_compress_rate=8,
            did=self.device_id,
            enable_asr_threepass=self.enable_asr_threepass,
            enable_asr_twopass=self.enable_asr_twopass,
            input_mode="tool",
        )

        return SessionConfig(
            audio_info=audio_info,
            enable_punctuation=self.enable_punctuation,
            enable_speech_rejection=self.enable_speech_rejection,
            extra=extra,
        )
    
    def get_token(self) -> str:
        self.ensure_credentials()
        return self.token