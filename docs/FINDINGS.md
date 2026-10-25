# 豆包输入法 ASR 服务端特性实测结论（FINDINGS）

> 实测时间：2026-10。协议为逆向所得，服务端行为可能随时变化；本文所有结论均有
> 可复现实验脚本与日志支持（见文末"如何复现"）。供使用者避坑，避免二次踩坑。

## 1. 结果结构与断句（重要：影响文本合并正确性）

| 信号 | 实测结论 |
|---|---|
| `results[].is_interim` | `true` = 流式中间结果；**`false` 且无 `is_vad_finished` ≠ 断句**，只是两遍解码（twopass）的"阶段性确认"，之后同句还会继续出中间结果 |
| 真正的断句定稿 | `is_vad_finished=true`（或 `extra.nonstream_result`）的结果，即 `FINAL_RESULT` |
| `results[].index` | **恒为 0**，不能用作 utterance 序号 |
| 断句兜底信号 | 中间结果**文本长度大幅缩水**（如从 100+ 字掉到 1~5 字）= 新句开始，旧句以最后一条中间结果为准 |
| 空文本中间结果 | 静音期间服务器每 ~640ms 发一条**空文本**结果，展示层应过滤 |

**正确合并算法**：`FINAL_RESULT` 权威提交；收到"长度重置"的中间结果时，把旧句以
最后中间结果提交。`transcribe()` 已按此逻辑修复（见下"代码修复"）。

## 2. 时间戳不可靠，进度看 `extra.audio_duration`

- 结果级 `start_time/end_time` 与 `alternatives[].words[].*` 时间戳**均不可靠**：
  nonstream 结果的 `end_time` 会 ×2（60s 音频报 120s）；长会话中甚至一路涨到
  超过音频总长（600s 音频报出 114s+）。
- **唯一可靠的进度信号是 `extra.audio_duration`（毫秒）**：服务器已消费的音频量，
  实测 60s 音频最终报 59980ms，且静音期间也持续更新。需要"服务器吃到哪了"的
  场景（限速、断点续传、进度条）请用它。

## 3. 发送速率：上限 ~6.4x，禁止瞬间倾倒

- 客户端不限速瞬间发完时，服务端消费速率从 3x 渐进爬升到 **~6.4x 后封顶**；
  多发的只是堆在链路缓冲里。
- **瞬间倾倒会触发 `rpc error: code=13 RST_STREAM NO_ERROR` 被断流**：
  600s 音频一次性灌入，服务端消费到 436.28s 时被网关断开，之后所有内容丢失，
  且无 SessionFinished。这是"伪会话时长上限"，真凶是缓冲堆积。
- 匀速 6x 发送时单会话连续消费 597s（≈10 分钟）无任何异常。

## 4. 空闲与静音：服务端非常宽容

| 场景 | 实测 |
|---|---|
| 150s 完全不发任何字节 | 会话存活，无超时断开 |
| 480s 持续发送纯静音 PCM | 会话存活，静音期间仅产空文本结果 |
| VAD 断句阈值 | 语音后 ~1.5~2s 静音即出该句 FINAL |

因此：暂停/断续场景**无需发静音保活**，也无需心跳造流量（`x-custom-keepalive`
的心跳已足够）。

## 5. 断点接力（换会话续传）

- 会话中途硬断（不发 FinishSession）→ 已返回的结果全部有效；
- 新会话从"服务器确认消费位置 **回退 2s**"处继续喂，接缝实测**零重复句**、语义连续；
- 正常发完生成器结束（FinishSession）→ `SessionFinished` + 末句 FINAL 正常到达，
  属于零损失的干净收尾，可放心用作定期轮换。

## 6. 代码修复（随本文一并提交）

`doubaoime_asr/asr.py`：

1. 新增 `ResponseType.TWO_PASS_RESULT`：`is_interim=false` 且无 `is_vad_finished`
   的结果不再混入 `INTERIM_RESULT`（原实现会丢失"阶段性确认"语义，导致上层无法
   区分检查点与普通中间结果）。
2. `ASRResponse` 新增 `two_pass` 与 `audio_duration_ms` 字段（后者为唯一可靠
   进度信号，免去了人人都要去 parse `raw_json` 的麻烦）。
3. 修复 `transcribe()` 丢字问题：原实现 `final_text = response.text` 只保留
   **最后一条** FINAL——多句音频只返回最后一句（60s 样本实测只返回 20 字，丢掉
   前面 230+ 字）。现按"FINAL 权威 + 长度重置兜底"合并全部句子。

## 如何复现

实验脚本与原始日志位于独立项目 `doubao-live-asr`（分离式实时转写系统）：
`experiments/e01~e04*.py` 与 `experiments/logs/*.jsonl`，结论文档
`experiments/REPORT.md`（中文）。
