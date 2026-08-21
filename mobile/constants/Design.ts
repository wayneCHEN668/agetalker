export const Design = {
  colors: {
    // 基础背景 — 暖暮色调
    background: '#FBF7F4', // 暖奶油色，护眼且温暖
    surface: '#FFFFFF',
    surfaceDim: '#F5F1ED',

    // 主色调：尘玫瑰 (Dusty Rose) — 温暖、疗愈、有质感
    primary: '#C17B6A',
    onPrimary: '#FFFFFF',
    primaryContainer: '#F5E4DE',
    onPrimaryContainer: '#3D231B',

    // 辅助色
    secondary: '#7A6E68',
    outline: '#E8E0DB',

    // 危机（仅真正高危时使用）
    crisis: '#D4453B',
    // 录音中状态（暖色调，不打断情感弧线）
    recording: '#7A6E68',
    // 正在聆听状态（暖琥珀）——StatusBar 圆点、Waveform 波形渐变共用
    listening: '#E8A838',

    // 情绪背景光晕 (Aura Colors) — 保持语义，调整色调与暖暮协调
    aura: {
      neutral:   ['#FBF7F4', '#ECE4DF'],
      happy:     ['#FFF2E6', '#FFDCC0'],
      sad:       ['#EBEBF0', '#D5D8E8'],
      angry:     ['#FDE8E5', '#F8CEC8'],
      fearful:   ['#F0E8EF', '#E0D0E4'],
      disgusted: ['#EEF0E6', '#DDE0CA'],
      surprised: ['#EAF0F5', '#D0DFEC'],
      // 危机：暖琥珀，取「安全感」而非「警报」。看到这个界面的是正处在
      // 危机中的老人本人，对他闪红色只会加重恐慌；红色留给护工侧的按钮点缀。
      crisis:    ['#FFF6EC', '#FFE2C4'],
    },

    text: {
      primary: '#2D2320',   // 暖调近黑，高对比度
      secondary: '#6B5E58',
      hint: '#8B7D76',
    },
  },
  typography: {
    fontFamily: 'Lexend_400Regular',
    display: {
      fontSize: 32,
      lineHeight: 40,
      fontWeight: '600' as const,
    },
    headline: {
      fontSize: 24,
      lineHeight: 32,
      fontWeight: '600' as const,
    },
    message: {
      fontSize: 18,
      lineHeight: 28,
    },
    label: {
      fontSize: 13,
      letterSpacing: 1.5,
      fontWeight: '500' as const,
    },
    caption: {
      fontSize: 14,
      lineHeight: 20,
      fontWeight: '400' as const,
    },
  },
  layout: {
    radius: 24,
    radiusSmall: 12,
    spacing: 24,
    innerPadding: 20,
  },
};
