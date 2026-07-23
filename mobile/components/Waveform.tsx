import React, { useEffect, useRef, useState } from 'react';
import { View, StyleSheet, Animated, Platform, LayoutChangeEvent } from 'react-native';
import { Design } from '../constants/Design';

interface WaveformProps {
  isActive: boolean;
  analyser?: AnalyserNode | null;
}

const BAR_COUNT = 7;

const NativeBars: React.FC<{ isActive: boolean }> = ({ isActive }) => {
  const anims = useRef(
    [...Array(BAR_COUNT)].map(() => new Animated.Value(1)),
  ).current;

  useEffect(() => {
    if (isActive) {
      const loops = anims.map((anim, i) =>
        Animated.loop(
          Animated.sequence([
            Animated.timing(anim, {
              toValue: 1.6 + Math.sin(i * 0.8) * 0.4,
              duration: 400 + i * 60,
              useNativeDriver: true,
            }),
            Animated.timing(anim, {
              toValue: 1,
              duration: 400 + i * 60,
              useNativeDriver: true,
            }),
          ]),
        ),
      );
      loops.forEach((l) => l.start());
      return () => loops.forEach((l) => l.stop());
    } else {
      anims.forEach((a) => a.setValue(1));
    }
  }, [isActive]);

  return (
    <View style={styles.barContainer}>
      {anims.map((anim, i) => (
        <Animated.View
          key={i}
          style={[
            styles.bar,
            {
              height: 24 + (i % 3) * 12,
              opacity: 0.45 + (i % 4) * 0.15,
              transform: [{ scaleY: anim }],
            },
          ]}
        />
      ))}
    </View>
  );
};

export const Waveform: React.FC<WaveformProps> = ({ isActive, analyser }) => {
  const canvasRef = useRef<any>(null);
  const requestRef = useRef<number | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  const onLayout = (event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    setDimensions({ width, height });
  };

  useEffect(() => {
    if (
      Platform.OS !== 'web' ||
      !isActive ||
      !analyser ||
      !canvasRef.current ||
      dimensions.width === 0
    ) {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
      return;
    }

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    canvas.width = dimensions.width;
    canvas.height = dimensions.height;

    const draw = () => {
      requestRef.current = requestAnimationFrame(draw);
      analyser.getByteTimeDomainData(dataArray);

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Warm Twilight gradient: dusty rose to warm amber
      const gradient = ctx.createLinearGradient(0, 0, canvas.width, 0);
      gradient.addColorStop(0, Design.colors.primary);
      gradient.addColorStop(0.5, '#E8A838');
      gradient.addColorStop(1, Design.colors.primary);

      const drawWave = (offset: number, alpha: number, lineWidth: number) => {
        ctx.beginPath();
        ctx.lineWidth = lineWidth;
        ctx.strokeStyle = gradient;
        ctx.globalAlpha = alpha;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';

        ctx.shadowBlur = isActive ? 12 : 0;
        ctx.shadowColor = Design.colors.primary;

        const sliceWidth = canvas.width / bufferLength;
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
          const v = dataArray[i] / 128.0;
          const y = (v * canvas.height) / 2 + offset;

          if (i === 0) {
            ctx.moveTo(x, y);
          } else {
            ctx.lineTo(x, y);
          }
          x += sliceWidth;
        }
        ctx.lineTo(canvas.width, canvas.height / 2);
        ctx.stroke();
      };

      drawWave(2, 0.25, 2);
      drawWave(0, 1, 3);
    };

    draw();

    return () => {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
    };
  }, [isActive, analyser, dimensions]);

  if (Platform.OS === 'web') {
    return (
      <View style={[styles.container, !isActive && styles.containerIdle]} onLayout={onLayout}>
        {isActive && (
          <canvas
            ref={canvasRef}
            style={{ width: '100%', height: '100%' }}
          />
        )}
        {!isActive && <View style={styles.idleLine} />}
      </View>
    );
  }

  return (
    <View style={[styles.container, !isActive && styles.containerIdle]}>
      {isActive ? <NativeBars isActive={isActive} /> : <View style={styles.idleLine} />}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    height: 100,
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    marginVertical: 16,
  },
  barContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  bar: {
    width: 5,
    height: 30,
    backgroundColor: Design.colors.primary,
    borderRadius: 3,
  },
  containerIdle: {
    height: 40,
    marginVertical: 8,
  },
  idleLine: {
    width: 60,
    height: 2,
    borderRadius: 1,
    backgroundColor: Design.colors.outline,
  },
});
