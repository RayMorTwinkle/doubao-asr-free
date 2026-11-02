"""Reproducible protocol capture, with bounded PCM feeding. No bundled private audio."""
import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import sys
import time
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from doubaoime_asr import DoubaoASR
from doubaoime_asr.asr import ResponseType
from doubaoime_asr.config import ASRConfig


async def inspect(args):
    counts=Counter()
    clean=False
    duration=0
    began=time.monotonic()
    async def feed():
        with wave.open(args.audio) as w:
            if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2):
                raise ValueError('Input must be 16 kHz, mono, 16-bit PCM WAV')
            w.setpos(int(args.start*16000))
            remaining=int(args.duration*16000) if args.duration else w.getnframes()-w.tell()
            deadline=time.monotonic()
            while remaining>0:
                data=w.readframes(min(1600,remaining))
                if not data:break
                yield data
                remaining-=len(data)//2
                deadline+=len(data)/32000/args.speed
                await asyncio.sleep(max(0,deadline-time.monotonic()))
    client=DoubaoASR(ASRConfig(credential_path=args.credential,recv_timeout=20))
    with Path(args.log).open('w') as log:
        async for response in client.transcribe_realtime(feed()):
            counts[response.type.name]+=1
            duration=max(duration,response.audio_duration_ms)
            log.write(json.dumps(dict(t=round(time.monotonic()-began,3),type=response.type.name,
                text=response.text,raw=response.raw_json,error=response.error_msg),ensure_ascii=False)+'\n')
            log.flush()
            clean |= response.type==ResponseType.SESSION_FINISHED
    print(json.dumps(dict(clean_finish=clean,counts=dict(counts),consumed_ms=duration,log=args.log),ensure_ascii=False))
    return 0 if clean and not counts['ERROR'] else 1


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('audio')
    ap.add_argument('--speed',type=float,default=1)
    ap.add_argument('--start',type=float,default=0)
    ap.add_argument('--duration',type=float)
    ap.add_argument('--log',default='stream-capture.jsonl')
    ap.add_argument('--credential',default='credentials.json')
    args=ap.parse_args()
    if not 0<args.speed<=6 or args.start<0 or (args.duration is not None and args.duration<=0):
        ap.error('speed must be in (0,6], start >=0, duration >0')
    sys.exit(asyncio.run(inspect(args)))
