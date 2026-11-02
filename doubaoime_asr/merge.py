"""Merge observed streaming revisions, without treating text prefixes as IDs.

Server timestamps are hints for associating revisions within ONE session only.
They must not be used as durable audio coverage or restart checkpoints.
"""
from difflib import SequenceMatcher
import re


def normalize(text):
    return re.sub(r'[^\w]', '', text).lower()


def related(a, b):
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return False
    n = min(12, len(a), len(b))
    return (n >= 6 and a[:n] == b[:n]) or SequenceMatcher(None, a, b, autojunk=False).ratio() >= .65


class StreamingMerger:
    def __init__(self):
        self.items = []
        self.current = None
        self.conflicts = []
        self._by_index = {}
        self._closed_indexes = set()
        self._max_index = -1
        self._last_signature = {}

    def _conflict(self, reason, result, audio_ms):
        record=dict(reason=reason,text=result.get('text',''),result_index=result.get('index'),
                    start_hint=result.get('start_time'),audio_ms=audio_ms)
        if not self.conflicts or self.conflicts[-1] != record:
            self.conflicts.append(record)

    def accept_response(self, response, *, audio_ms=0):
        raw = response.raw_json or {}
        if isinstance(raw.get('results'),list):
            for result in raw['results']:
                self.accept_result(result,audio_ms=audio_ms)
        else:
            self.accept(response.text,audio_ms=audio_ms,final=response.is_final)

    def accept_result(self, result, *, audio_ms=0):
        """Associate with (VAD index, local piece counter), preserving ambiguity.

        The piece counter advances on an empty-alternative boundary, or a
        force-finished checkpoint followed by a distinct starting region.
        A sentence merely getting shorter or different is not a boundary.
        See experiments/protocol_audit.py and the controlled wire captures.
        """
        index=result.get('index')
        text=result.get('text','') or ''
        start=result.get('start_time')
        final=bool(result.get('is_vad_finished') and result.get('is_interim') is False
                   or (result.get('extra') or {}).get('nonstream_result'))
        if not isinstance(index,int) or isinstance(index,bool) or index<0:
            if self._by_index:
                self._conflict('missing_index_after_indexed_results',result,audio_ms)
            else:
                self.accept(text,start=start,audio_ms=audio_ms,final=final)
            return
        signature=(text,start,audio_ms,str(result))
        if self._last_signature.get(index)==signature:
            return
        self._last_signature[index]=signature
        parts=self._by_index.get(index,[])
        if not text.strip():
            if result.get('is_vad_finished'):
                self._closed_indexes.add(index)
            return
        alternatives=result.get('alternatives') or []
        if len(alternatives)>1 and sum(bool(a.get('text')) for a in alternatives)>1:
            self._conflict('unverified_multiple_nonempty_alternatives',result,audio_ms)
            return
        historical=index<self._max_index or index in self._closed_indexes
        if historical and (len(parts)!=1 or not final):
            self._conflict('late_update_has_no_unique_piece_id',result,audio_ms)
            return
        target=self.items[parts[-1]] if parts else None
        if target and not historical:
            # A return to a closed piece's starting region is an anomaly, not
            # permission to overwrite the active piece. Time is only an alarm.
            older=parts if target.get('piece_closed') else parts[:-1]
            if isinstance(start,(int,float)) and any(
                self.items[i]['min_start'] is not None and
                self.items[i]['min_start']-1<=start<=self.items[i]['max_start']+1 for i in older):
                self._conflict('possible_late_piece_update_without_piece_id',result,audio_ms)
                return
            forced_new_region=(target.get('force_checkpoint') and isinstance(start,(int,float))
                and target['max_start'] is not None and start>target['max_start']+1
                and len(text)<len(target['text']))
            if target.get('piece_closed') or forced_new_region:
                target=None
        if index>self._max_index:
            if self._max_index>=0:self._closed_indexes.add(self._max_index)
            self._max_index=index
        if target is None:
            target=dict(text=text,min_start=start,max_start=start,first_ms=audio_ms,last_ms=audio_ms,
                        final=final,result_index=index,part_index=len(parts),piece_closed=False,
                        force_checkpoint=False,association='protocol_index_and_piece_boundaries')
            self.items.append(target)
            self.current=len(self.items)-1
            self._by_index.setdefault(index,[]).append(self.current)
        else:
            if final or not target['final']:target['text']=text
            target['final']|=final
            target['last_ms']=max(target['last_ms'],audio_ms)
            if start is not None:
                target['min_start']=min(target['min_start'],start) if target['min_start'] is not None else start
                target['max_start']=max(target['max_start'],start) if target['max_start'] is not None else start
        if len(alternatives)>1 and not alternatives[-1].get('text'):
            target['piece_closed']=True
        target['force_checkpoint']=bool(result.get('is_force_finished'))
        if result.get('is_vad_finished'):
            self._closed_indexes.add(index)

    def accept(self, text, *, start=None, audio_ms=0, final=False):
        if not text.strip():
            return  # Empty FINAL must not discard a different pending utterance.
        current = self.items[self.current] if self.current is not None else None
        target = None
        # Recover late revisions of an earlier interleaved utterance.
        if isinstance(start, (int, float)):
            for item in reversed(self.items):
                if (item['min_start'] is not None and item['min_start']-1 <= start <= item['max_start']+1
                        and related(item['text'], text)):
                    target = item
                    break
        if target is None and current:
            if (start is not None and current['min_start'] is not None
                    and start < current['min_start']-1):
                self._conflict('unmatched_backward_update_without_protocol_index',
                               dict(text=text,start_time=start),audio_ms)
                return
            boundary = (len(text)*2 < len(current['text']) or
                (start is not None and current['min_start'] is not None
                 and start > current['min_start']+1 and (len(text) < len(current['text'])
                    or (final and not related(current['text'],text)))))
            # Identical speech at a later source position is a real repetition.
            later = (start is not None and current['last_ms'] > 0
                     and start > current['last_ms']/1000 + .5
                     and audio_ms-current['last_ms'] > 2000)
            if not later and (not boundary or (final and start is not None and
                    current['min_start'] is not None and
                    current['min_start']-1 <= start <= current['max_start']+1)):
                target = current
        if target is None:
            target = dict(text=text, min_start=start, max_start=start,
                          first_ms=audio_ms, last_ms=audio_ms, final=final)
            self.items.append(target)
            self.current = len(self.items)-1
        else:
            # Finals can correct or shorten a draft; subsequent interim messages
            # cannot overwrite an authoritative final.
            if final or not target['final']:
                target['text'] = text
            target['final'] = target['final'] or final
            target['last_ms'] = max(target['last_ms'], audio_ms)
            if start is not None:
                target['min_start'] = min(target['min_start'], start) if target['min_start'] is not None else start
                target['max_start'] = max(target['max_start'], start) if target['max_start'] is not None else start

    def text(self):
        return ''.join(self._display_texts())

    def _display_texts(self):
        texts=[item['text'] for item in self.items]
        for i in range(1,len(self.items)):
            previous,current=self.items[i-1:i+1]
            # Some VAD finals contain a long suffix already emitted as the
            # preceding fallback. Require BOTH overlapping source hints and
            # a substantial exact normalized suffix/prefix; never dedup merely
            # because two sentences happen to begin with the same words.
            if previous.get('result_index') is not None and current.get('result_index') is not None:
                if previous['result_index']!=current['result_index']:
                    continue  # Repeated speech in a new VAD segment is real speech.
            if current['min_start'] is None or previous['last_ms']/1000-current['min_start']<1:
                continue
            a,b=normalize(previous['text']),normalize(current['text'])
            size=next((n for n in range(min(len(a),len(b)),11,-1) if a[-n:]==b[:n]),0)
            if size:
                indexes=[j for j,c in enumerate(current['text']) if re.match(r'\w',c)]
                texts[i]=current['text'][indexes[size-1]+1:].lstrip('，。！？、；：,.!?;: ')
        return texts

    def rows(self, session_start=0, bps=32000):
        # Observation coordinates, explicitly NOT claimed as exact word timing.
        return [dict(text=text, raw_text=r['text'], start_pcm=session_start+int(r['first_ms']*bps/1000),
                     end_pcm=session_start+int(r['last_ms']*bps/1000), final=r['final'],
                     timing='response_observation',result_index=r.get('result_index'),
                     part_index=r.get('part_index'),association=r.get('association','legacy_heuristic'))
                for r,text in zip(self.items,self._display_texts()) if text]
