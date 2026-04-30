import React, { useEffect, useRef, useState } from 'react';
import { View, StyleSheet, Animated, Platform, LayoutChangeEvent } from 'react-native';
import { Design } from '../constants/Design';

interface WaveformProps {
  isActive: boolean;
  analyser?: AnalyserNode | null;
}

export const Waveform: React.FC<WaveformProps> = ({ isActive, analyser }) => {
  const canvasRef = useRef<any>(null);
  const requestRef = useRef<number | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const anim = useRef(new Animated.Value(1)).current;

  // Fallback animation for Native
  useEffect(() => {
    if (Platform.OS !== 'web') {
      if (isActive) {
        Animated.loop(
          Animated.sequence([
            Animated.timing(anim, { toValue: 2, duration: 500, useNativeDriver: true }),
            Animated.timing(anim, { toValue: 1, duration: 500, useNativeDriver: true }),
          ])
        ).start();
      } else {
        anim.setValue(1);
      }
    }
  }, [isActive]);

  const onLayout = (event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    setDimensions({ width, height });
  };

  useEffect(() => {
    if (Platform.OS !== 'web' || !isActive || !analyser || !canvasRef.current || dimensions.width === 0) {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
      return;
    }

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    // Set canvas internal resolution to match layout size
    canvas.width = dimensions.width;
    canvas.height = dimensions.height;

    const draw = () => {
      requestRef.current = requestAnimationFrame(draw);
      analyser.getByteTimeDomainData(dataArray);

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Gradient for the wave
      const gradient = ctx.createLinearGradient(0, 0, canvas.width, 0);
      gradient.addColorStop(0, Design.colors.primary);
      gradient.addColorStop(0.5, '#4FC3F7'); // Lighter blue
      gradient.addColorStop(1, Design.colors.primary);

      // Draw two layers for depth
      const drawWave = (offset: number, alpha: number, lineWidth: number) => {
        ctx.beginPath();
        ctx.lineWidth = lineWidth;
        ctx.strokeStyle = gradient;
        ctx.globalAlpha = alpha;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';

        // Glow effect
        ctx.shadowBlur = isActive ? 15 : 0;
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

      // Background layer
      drawWave(2, 0.3, 2);
      // Foreground layer
      drawWave(0, 1, 3);
    };

    draw();

    return () => {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
    };
  }, [isActive, analyser, dimensions]);

  if (Platform.OS === 'web') {
    return (
      <View style={styles.container} onLayout={onLayout}>
        <canvas
          ref={canvasRef}
          style={{
            width: '100%',
            height: '100%',
          }}
        />
      </View>
    );
  }

  // Native Fallback
  return (
    <View style={styles.container}>
      {[...Array(5)].map((_, i) => (
        <Animated.View
          key={i}
          style={[
            styles.bar,
            { transform: [{ scaleY: isActive ? anim : 1 }] }
          ]}
        />
      ))}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    height: 120,
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginVertical: 20,
  },
  bar: {
    width: 6,
    height: 40,
    backgroundColor: Design.colors.primary,
    borderRadius: 3,
  },
});
