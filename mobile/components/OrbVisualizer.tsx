import React, { useEffect, useMemo, useRef, useState } from 'react';
import { View, StyleSheet, Animated, Platform, LayoutChangeEvent } from 'react-native';
import type { AnalyserNode } from 'react-native-audio-api';
import { Design } from '../constants/Design';

/**
 * 聊天页的抽象可视化模式：不展示文字对话，只展示一个由多层同心点阵组成的圆。
 *
 * 四态靠"运动的性质"区分，而不是靠"动/不动"——完全静止的画面会让老人分不清
 * "AI 正在说话"和"程序卡死了"：
 *   idle      —— 极慢整体呼吸，振幅很小，"醒着但闲着"
 *   listening —— 每个点的大小跟麦克风实时频谱走，按角度分桶，有方向感
 *   thinking  —— 点大小锁死，各层以不同速度极慢公转，"在忙，但还没话说"
 *   speaking  —— 点大小锁死，叠加从圆心向外扩散的涟漪，"声音从这里发出来"
 *
 * 优先级 speaking > thinking > listening > idle：TTS 播放时 ASR 只是被静音
 * （回声消除），status 仍可能是 'listening'，说话态必须压过听态。
 */

export type OrbPhase = 'idle' | 'listening' | 'thinking' | 'speaking';

export function derivePhase(params: {
  isPlaying: boolean;
  isLLMStreaming: boolean;
  asrStatus: 'idle' | 'listening' | 'processing' | 'reconnecting';
}): OrbPhase {
  if (params.isPlaying) return 'speaking';
  if (params.isLLMStreaming || params.asrStatus === 'processing') return 'thinking';
  if (params.asrStatus === 'listening') return 'listening';
  return 'idle';
}

interface OrbVisualizerProps {
  phase: OrbPhase;
  analyser?: AnalyserNode | null;
  /** [浅色, 深色] —— 直接吃 index.tsx 现有的情绪光晕色，颜色跟着情绪/危机态走 */
  auraColors: readonly string[];
}

// 同心环几何：由内向外，点数递增、单点尺寸递减——密的小点在外圈，
// 疏的大点在内圈，避免"整齐的靶心"感。
const RING_RADIUS_RATIOS = [0.28, 0.52, 0.76, 1.0];
const RING_POINT_COUNTS = [8, 14, 20, 26];
const RING_SIZE_RATIOS = [0.095, 0.075, 0.058, 0.044];
// 公转态：各层不同速度、不同方向，rad/ms
const RING_ROTATE_SPEED = [0.00016, -0.00011, 0.00008, -0.00006];

const hexToRgb = (hex: string) => {
  const n = parseInt(hex.replace('#', ''), 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
};

const mixHex = (a: string, b: string, t: number): string => {
  const ca = hexToRgb(a);
  const cb = hexToRgb(b);
  const r = Math.round(ca.r + (cb.r - ca.r) * t);
  const g = Math.round(ca.g + (cb.g - ca.g) * t);
  const bl = Math.round(ca.b + (cb.b - ca.b) * t);
  return `rgb(${r}, ${g}, ${bl})`;
};

// ─── Web: canvas + requestAnimationFrame ───────────────────────────────────

const WebOrb: React.FC<{
  phase: OrbPhase;
  analyser?: AnalyserNode | null;
  dotColor: string;
  size: number;
}> = ({ phase, analyser, dotColor, size }) => {
  const canvasRef = useRef<any>(null);
  const requestRef = useRef<number | null>(null);
  // 每个点独立的平滑读数（逐帧向目标值插值，避免频谱直取抖成噪点）
  const smoothedRef = useRef<Float32Array>(
    new Float32Array(RING_POINT_COUNTS.reduce((a, b) => a + b, 0)),
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || size === 0) return;
    const ctx = canvas.getContext('2d');
    canvas.width = size;
    canvas.height = size;

    const cx = size / 2;
    const cy = size / 2;
    const maxRadius = size * 0.5 * 0.55;
    const rippleMaxRadius = size * 0.5 * 0.95;
    const startTime = performance.now();

    // 涟漪状态必须是本次 effect 运行的局部变量，不能用 useRef 跨运行存活：
    // startTime 每次重跑都重置，而 phase 一变 effect 就重跑，跨运行留下来的
    // 时间戳属于已经作废的时间轴，会让 elapsed - born 变成大负数，
    // 进而算出负的涟漪半径把 canvas 的 arc() 打挂。
    let ripples: number[] = [];
    // 置负数使得进入说话态的第一帧就立刻放出一圈涟漪，而不是先等 900ms
    let lastRippleSpawn = -Infinity;

    const bufferLength = analyser?.frequencyBinCount ?? 0;
    const halfCount = Math.floor(bufferLength * 0.5);
    const freqData = bufferLength > 0 ? new Uint8Array(bufferLength) : null;

    // 角度 0 = 正下方，向两侧对称展开，正上方汇合——低频在下，高频在上
    const binForAngle = (angle: number): number => {
      const a = ((angle % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
      const fromBottom = ((a - Math.PI / 2 + Math.PI * 2) % (Math.PI * 2));
      const mirrored = fromBottom <= Math.PI ? fromBottom : Math.PI * 2 - fromBottom;
      const t = mirrored / Math.PI;
      return Math.min(halfCount - 1, Math.max(0, Math.floor(t * halfCount)));
    };

    const draw = (now: number) => {
      requestRef.current = requestAnimationFrame(draw);
      const elapsed = now - startTime;

      ctx.clearRect(0, 0, size, size);

      // 说话态：从圆心向外扩散的涟漪，画在点阵下方
      if (phase === 'speaking') {
        const spawnInterval = 900;
        const lifetime = 1400;
        if (elapsed - lastRippleSpawn >= spawnInterval) {
          lastRippleSpawn = elapsed;
          ripples.push(elapsed);
        }
        ripples = ripples.filter((t) => elapsed - t < lifetime);
        for (const born of ripples) {
          const progress = (elapsed - born) / lifetime;
          const r = rippleMaxRadius * progress;
          ctx.beginPath();
          ctx.arc(cx, cy, r, 0, Math.PI * 2);
          ctx.strokeStyle = dotColor;
          ctx.globalAlpha = Math.max(0, (1 - progress) * 0.35);
          ctx.lineWidth = 2;
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }

      if (phase === 'listening' && freqData && analyser) {
        analyser.getByteFrequencyData(freqData);
      }

      let dotIdx = 0;
      RING_RADIUS_RATIOS.forEach((radiusRatio, ringIdx) => {
        const ringRadius = maxRadius * radiusRatio;
        const count = RING_POINT_COUNTS[ringIdx];
        const baseDotSize = size * RING_SIZE_RATIOS[ringIdx];
        const rotateOffset = elapsed * RING_ROTATE_SPEED[ringIdx];

        for (let i = 0; i < count; i++) {
          const baseTheta = (i / count) * Math.PI * 2;
          let theta = baseTheta;
          let dotSize = baseDotSize;

          if (phase === 'idle') {
            const breathe = Math.sin(elapsed * 0.0013 + ringIdx * 0.5) * 0.06;
            dotSize = baseDotSize * (1 + breathe);
          } else if (phase === 'thinking') {
            theta = baseTheta + rotateOffset;
          } else if (phase === 'listening' && freqData) {
            theta = baseTheta;
            const bin = binForAngle(theta);
            const target = freqData[bin] / 255;
            smoothedRef.current[dotIdx] += (target - smoothedRef.current[dotIdx]) * 0.3;
            dotSize = baseDotSize * (1 + smoothedRef.current[dotIdx] * 1.8);
          }
          // speaking: 大小锁死为 baseDotSize，位置锁死为 baseTheta

          const x = cx + Math.cos(theta) * ringRadius;
          const y = cy + Math.sin(theta) * ringRadius;

          ctx.beginPath();
          ctx.arc(x, y, dotSize / 2, 0, Math.PI * 2);
          ctx.fillStyle = dotColor;
          ctx.globalAlpha = 0.55 + (1 - ringIdx / RING_RADIUS_RATIOS.length) * 0.3;
          ctx.fill();
          dotIdx++;
        }
      });
      ctx.globalAlpha = 1;
    };

    requestRef.current = requestAnimationFrame(draw);

    return () => {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
    };
  }, [phase, analyser, dotColor, size]);

  return <canvas ref={canvasRef} style={{ width: size, height: size }} />;
};

// ─── Native: 预计算点位 + Animated（无 analyser，降级为程序化动画） ─────────

const NativeOrb: React.FC<{ phase: OrbPhase; dotColor: string; size: number }> = ({
  phase,
  dotColor,
  size,
}) => {
  const maxRadius = size * 0.5 * 0.55;
  const rippleMaxRadius = size * 0.5 * 0.95;

  // 每层一个共享 Animated.Value：驱动该层全部点的呼吸/抖动幅度
  const ringAnims = useRef(RING_RADIUS_RATIOS.map(() => new Animated.Value(0))).current;
  const rotateAnims = useRef(RING_RADIUS_RATIOS.map(() => new Animated.Value(0))).current;
  const rippleAnims = useRef([0, 1, 2].map(() => new Animated.Value(0))).current;

  useEffect(() => {
    const loops: Animated.CompositeAnimation[] = [];

    if (phase === 'idle') {
      ringAnims.forEach((anim, i) => {
        const loop = Animated.loop(
          Animated.sequence([
            Animated.delay(i * 150),
            Animated.timing(anim, { toValue: 1, duration: 2500, useNativeDriver: true }),
            Animated.timing(anim, { toValue: 0, duration: 2500, useNativeDriver: true }),
          ]),
        );
        loop.start();
        loops.push(loop);
      });
    } else if (phase === 'listening') {
      ringAnims.forEach((anim, i) => {
        const loop = Animated.loop(
          Animated.sequence([
            Animated.timing(anim, { toValue: 1, duration: 260 + i * 40, useNativeDriver: true }),
            Animated.timing(anim, { toValue: 0.15, duration: 260 + i * 40, useNativeDriver: true }),
          ]),
        );
        loop.start();
        loops.push(loop);
      });
    } else if (phase === 'thinking') {
      ringAnims.forEach((anim) => anim.setValue(0));
      rotateAnims.forEach((anim, i) => {
        anim.setValue(0);
        const duration = 14000 + i * 3000;
        const loop = Animated.loop(
          Animated.timing(anim, { toValue: 1, duration, useNativeDriver: true }),
        );
        loop.start();
        loops.push(loop);
      });
    } else if (phase === 'speaking') {
      ringAnims.forEach((anim) => anim.setValue(0));
      rippleAnims.forEach((anim, i) => {
        anim.setValue(0);
        const loop = Animated.loop(
          Animated.sequence([
            Animated.delay(i * 450),
            Animated.timing(anim, { toValue: 1, duration: 1400, useNativeDriver: true }),
          ]),
        );
        loop.start();
        loops.push(loop);
      });
    }

    return () => {
      loops.forEach((l) => l.stop());
      ringAnims.forEach((anim) => anim.setValue(0));
      rotateAnims.forEach((anim) => anim.setValue(0));
      rippleAnims.forEach((anim) => anim.setValue(0));
    };
  }, [phase]);

  return (
    <View style={{ width: size, height: size }}>
      {phase === 'speaking' &&
        rippleAnims.map((anim, i) => (
          <Animated.View
            key={`ripple-${i}`}
            pointerEvents="none"
            style={[
              styles.ripple,
              {
                width: rippleMaxRadius * 2,
                height: rippleMaxRadius * 2,
                borderRadius: rippleMaxRadius,
                borderColor: dotColor,
                left: size / 2 - rippleMaxRadius,
                top: size / 2 - rippleMaxRadius,
                opacity: anim.interpolate({ inputRange: [0, 1], outputRange: [0.35, 0] }),
                transform: [
                  { scale: anim.interpolate({ inputRange: [0, 1], outputRange: [0.15, 1] }) },
                ],
              },
            ]}
          />
        ))}
      {RING_RADIUS_RATIOS.map((radiusRatio, ringIdx) => {
        const ringRadius = maxRadius * radiusRatio;
        const count = RING_POINT_COUNTS[ringIdx];
        const baseDotSize = size * RING_SIZE_RATIOS[ringIdx];
        const opacity = 0.55 + (1 - ringIdx / RING_RADIUS_RATIOS.length) * 0.3;

        const scale =
          phase === 'idle' || phase === 'listening'
            ? ringAnims[ringIdx].interpolate({
                inputRange: [0, 1],
                outputRange: phase === 'idle' ? [0.94, 1.06] : [1, 1.7],
              })
            : 1;

        const rotate =
          phase === 'thinking'
            ? rotateAnims[ringIdx].interpolate({
                inputRange: [0, 1],
                outputRange:
                  RING_ROTATE_SPEED[ringIdx] > 0 ? ['0deg', '360deg'] : ['360deg', '0deg'],
              })
            : '0deg';

        return (
          <Animated.View
            key={ringIdx}
            pointerEvents="none"
            style={[
              StyleSheet.absoluteFill,
              { transform: [{ rotate }] },
            ]}
          >
            {Array.from({ length: count }).map((_, i) => {
              const theta = (i / count) * Math.PI * 2;
              const x = size / 2 + Math.cos(theta) * ringRadius - baseDotSize / 2;
              const y = size / 2 + Math.sin(theta) * ringRadius - baseDotSize / 2;
              return (
                <Animated.View
                  key={i}
                  style={{
                    position: 'absolute',
                    left: x,
                    top: y,
                    width: baseDotSize,
                    height: baseDotSize,
                    borderRadius: baseDotSize / 2,
                    backgroundColor: dotColor,
                    opacity,
                    transform: [{ scale }],
                  }}
                />
              );
            })}
          </Animated.View>
        );
      })}
    </View>
  );
};

export const OrbVisualizer: React.FC<OrbVisualizerProps> = ({ phase, analyser, auraColors }) => {
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const containerRef = useRef<View>(null);

  const onLayout = (event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    setDimensions({ width, height });
  };

  // Web 兜底：这一层是纯 flex 容器（没有固定高度），RN Web 的 onLayout
  // 在深层嵌套的 flex 链路上有时接不上 ResizeObserver，直接量 DOM 更可靠
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    const node = containerRef.current as unknown as HTMLElement | null;
    if (!node) return;
    const measure = () => {
      const rect = node.getBoundingClientRect();
      setDimensions({ width: rect.width, height: rect.height });
    };
    measure();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    return () => ro.disconnect();
  }, []);

  const dotColor = useMemo(
    () => mixHex(Design.colors.primary, auraColors[1] ?? auraColors[0] ?? Design.colors.primary, 0.35),
    [auraColors],
  );

  const size = Math.max(0, Math.min(dimensions.width, dimensions.height, 420) * 0.92);

  return (
    <View ref={containerRef} style={styles.container} onLayout={onLayout}>
      {size > 0 &&
        (Platform.OS === 'web' ? (
          <WebOrb phase={phase} analyser={analyser} dotColor={dotColor} size={size} />
        ) : (
          <NativeOrb phase={phase} dotColor={dotColor} size={size} />
        ))}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    minHeight: 0,
    alignItems: 'center',
    justifyContent: 'center',
  },
  ripple: {
    position: 'absolute',
    borderWidth: 2,
    borderStyle: 'solid',
  },
});
