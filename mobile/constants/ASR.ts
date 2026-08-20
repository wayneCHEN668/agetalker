/**
 * ASR 上行音频参数。
 *
 * ⚠️ 必须与后端 `backend/config.py` 的 ASR_SAMPLE_RATE / ASR_FRAME_SAMPLES
 * 严格一致，后端按这个约定切帧。
 *
 * 另外，`constants/BargeIn.ts` 里 SUSTAINED_FRAMES、PREBUFFER_FRAMES 的取值
 * 都是按「每帧约 128ms」推算的（2048 / 16000 ≈ 0.128s）。改这里的值会让那些
 * 注释里的毫秒推算全部失真，必须一并复核。
 */
export const ASR_SAMPLE_RATE = 16000;
export const ASR_FRAME_SAMPLES = 2048;
