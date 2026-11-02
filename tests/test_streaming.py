"""Self-contained regressions; synthetic text, no credentials or network needed."""
import asyncio
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from doubaoime_asr.asr import DoubaoASR,ASRResponse,ResponseType,ASRError
from doubaoime_asr.config import ASRConfig
from doubaoime_asr.merge import StreamingMerger


class MergeTests(unittest.TestCase):
    def test_protocol_index_routes_large_revision_to_first_of_three(self):
        m=StreamingMerger()
        for idx,text in enumerate(['今天下午四点在会议室开会','请大家提前十分钟到达现场','会议结束以后我们一起吃晚饭']):
            m.accept_result(dict(index=idx,text=text,start_time=idx*10,is_interim=True),audio_ms=(idx*10+5)*1000)
        revised='本次活动调整为线上视频讨论'
        m.accept_result(dict(index=0,text=revised,start_time=0,is_interim=False,is_vad_finished=True),audio_ms=27000)
        self.assertEqual([r['text'] for r in m.items],[revised,'请大家提前十分钟到达现场','会议结束以后我们一起吃晚饭'])

    def test_empty_alternative_opens_new_piece_without_text_guessing(self):
        m=StreamingMerger()
        for i,text in enumerate(['第一块文字','第二块文字','第三块文字']):
            m.accept_result(dict(index=0,text=text,start_time=i*30,is_interim=True,
                alternatives=[dict(text=text),dict(text='')]),audio_ms=(i*30+20)*1000)
        self.assertEqual([r['text'] for r in m.items],['第一块文字','第二块文字','第三块文字'])
        self.assertEqual([r['part_index'] for r in m.items],[0,1,2])

    def test_ambiguous_old_piece_never_overwrites_third_piece(self):
        m=StreamingMerger()
        for i,text in enumerate(['第一块文字','第二块文字','第三块文字']):
            m.accept_result(dict(index=0,text=text,start_time=i*30,is_interim=True,
                alternatives=[dict(text=text),dict(text='')] if i<2 else [dict(text=text)]),audio_ms=(i*30+20)*1000)
        m.accept_result(dict(index=0,text='第一块被彻底改写',start_time=0,is_interim=False),audio_ms=85000)
        self.assertEqual([r['text'] for r in m.items],['第一块文字','第二块文字','第三块文字'])
        self.assertEqual(len(m.conflicts),1)

    def test_timeout_flag_alone_does_not_end_piece(self):
        m=StreamingMerger()
        m.accept_result(dict(index=0,text='超时点',start_time=0,is_interim=True,is_vad_timeout=True),audio_ms=25000)
        m.accept_result(dict(index=0,text='超时点后还继续修订',start_time=0,is_interim=True),audio_ms=28000)
        self.assertEqual(len(m.items),1)
        self.assertEqual(m.items[0]['text'],'超时点后还继续修订')

    def test_force_finished_checkpoint_continues_when_start_region_is_same(self):
        m=StreamingMerger()
        m.accept_result(dict(index=0,text='阶段性文字',start_time=0,is_interim=False,is_force_finished=True),audio_ms=5000)
        m.accept_result(dict(index=0,text='阶段性文字还在增长',start_time=0,is_interim=True),audio_ms=10000)
        self.assertEqual([r['text'] for r in m.items],['阶段性文字还在增长'])

    def test_force_finished_followed_by_new_start_preserves_old_piece(self):
        m=StreamingMerger()
        m.accept_result(dict(index=0,text='旧片段仍须保留',start_time=26,is_interim=False,is_force_finished=True),audio_ms=60000)
        m.accept_result(dict(index=0,text='新片段',start_time=50,is_interim=True),audio_ms=61000)
        self.assertEqual([r['text'] for r in m.items],['旧片段仍须保留','新片段'])

    def test_empty_final_closes_index_without_erasing_its_text(self):
        m=StreamingMerger()
        m.accept_result(dict(index=5,text='保留这个语音段的文字',start_time=30,is_interim=True),audio_ms=40000)
        m.accept_result(dict(index=5,text='',is_interim=False,is_vad_finished=True),audio_ms=41000)
        m.accept_result(dict(index=6,text='下一段',start_time=42,is_interim=True),audio_ms=43000)
        self.assertEqual([r['text'] for r in m.items],['保留这个语音段的文字','下一段'])

    def test_final_revises_earlier_interleaved_draft(self):
        m=StreamingMerger()
        m.accept('第一句已经有很多字了，后面还会继续',start=0,audio_ms=5000)
        m.accept('第二句',start=6,audio_ms=7000)
        m.accept('',final=True)
        final='第一句已经有很多字了，后面还会继续，最后补全。'
        m.accept(final,start=0,audio_ms=8000,final=True)
        self.assertEqual(m.text(),final+'第二句')

    def test_identical_sentence_spoken_again_is_not_a_revision(self):
        m=StreamingMerger()
        for start in [0,20]:m.accept('这句需要重复保留',start=start,audio_ms=(start+10)*1000,final=True)
        self.assertEqual(len(m.items),2)

    def test_final_can_correct_and_shorten_current_draft(self):
        m=StreamingMerger()
        m.accept('第一句话包含很多识别错误需要修正',start=0,audio_ms=10000)
        m.accept('最终修正。',start=0,audio_ms=11000,final=True)
        self.assertEqual(m.text(),'最终修正。')

    def test_overlapping_vad_final_does_not_duplicate_long_suffix(self):
        overlap='当时在一个下午四点才开始'
        m=StreamingMerger()
        m.accept('记者一直在等待，'+overlap,start=20,audio_ms=60000)
        m.accept(overlap+'，这就是记者的日常。',start=50,audio_ms=63000,final=True)
        self.assertEqual(m.text(),'记者一直在等待，'+overlap+'这就是记者的日常。')
        self.assertEqual(m.rows()[-1]['raw_text'],overlap+'，这就是记者的日常。')


class TaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_receiver_reports_actual_parse_or_transport_error(self):
        from types import SimpleNamespace
        class BadSocket:
            async def recv(self):raise ValueError('malformed response')
        client=DoubaoASR(ASRConfig(device_id='test',token='test'))
        queue=asyncio.Queue()
        await client._receive_responses(BadSocket(),SimpleNamespace(is_finished=False),queue)
        response=queue.get_nowait()
        self.assertEqual(response.type,ResponseType.ERROR)
        self.assertIn('ValueError: malformed response',response.error_msg)

    async def test_sender_failure_propagates_without_waiting_for_receiver(self):
        async def fail():raise ValueError('broken source')
        send=asyncio.create_task(fail())
        recv=asyncio.create_task(asyncio.sleep(100))
        await asyncio.sleep(0)
        client=DoubaoASR(ASRConfig(device_id='test',token='test'))
        with self.assertRaisesRegex(ValueError,'broken source'):
            async for _ in client._task_responses(send,recv,asyncio.Queue()):pass
        self.assertTrue(recv.done())

    async def test_closed_receiver_cancels_idle_source_and_reports_incomplete(self):
        send=asyncio.create_task(asyncio.sleep(100))
        recv=asyncio.create_task(asyncio.sleep(100))
        queue=asyncio.Queue()
        queue.put_nowait(None)
        client=DoubaoASR(ASRConfig(device_id='test',token='test'))
        responses=[r async for r in client._task_responses(send,recv,queue)]
        self.assertEqual(responses[0].type,ResponseType.ERROR)
        self.assertTrue(send.done())

    async def test_clean_finish_is_not_reported_as_error(self):
        send=asyncio.create_task(asyncio.sleep(100))
        recv=asyncio.create_task(asyncio.sleep(100))
        queue=asyncio.Queue()
        queue.put_nowait(ASRResponse(ResponseType.SESSION_FINISHED))
        queue.put_nowait(None)
        client=DoubaoASR(ASRConfig(device_id='test',token='test'))
        responses=[r async for r in client._task_responses(send,recv,queue)]
        self.assertEqual([r.type for r in responses],[ResponseType.SESSION_FINISHED])


if __name__=='__main__':unittest.main()
