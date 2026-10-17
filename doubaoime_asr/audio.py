from typing import Optional, List, Union
from pathlib import Path

import opuslib
import miniaudio

from .config import ASRConfig



class AudioEncoder:
    """
    进行音频格式转换
    """
    def __init__(self, config: ASRConfig) -> None:
        self.config = config
        self._encoder: Optional[opuslib.Encoder] = None
    
    @property
    def encoder(self) -> opuslib.Encoder:
        if self._encoder is None:
            self._encoder = opuslib.Encoder(
                self.config.sample_rate,
                self.config.channels,
                opuslib.APPLICATION_AUDIO,
            )
        return self._encoder
    
    def pcm_to_opus_frames(self, pcm_data: bytes) -> List[bytes]:
        samples_per_frame = (
            self.config.sample_rate * self.config.frame_duration_ms // 1000
        )
        bytes_per_frame = samples_per_frame * 2 # 16-bit

        frames = []
        for i in range(0, len(pcm_data), bytes_per_frame):
            chunk = pcm_data[i : i + bytes_per_frame]
            if len(chunk) < bytes_per_frame:
                chunk = chunk + b"\x00" * (bytes_per_frame - len(chunk))
            
            opus_frame = self.encoder.encode(chunk, samples_per_frame)
            frames.append(opus_frame)
        
        return frames
    
    @staticmethod
    def convert_audio_to_pcm(
        audio_path: Union[Path, str],
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> bytes:
        decoded = miniaudio.decode_file(
            str(audio_path),
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=channels,
            sample_rate=sample_rate,
        )
        return decoded.samples.tobytes()
