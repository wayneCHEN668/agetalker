export const Design = {
  colors: {
    // 基础背景
    background: '#FAF9F6', // 暖沙色，护眼且温馨
    surface: '#FFFFFF',
    surfaceDim: '#F0EFEA',
    
    // 主色调：愈疗绿 (Sage)
    primary: '#4A6741',      // 深鼠尾草绿，沉稳可靠
    onPrimary: '#FFFFFF',
    primaryContainer: '#E8F5E9',
    onPrimaryContainer: '#1B2E16',
    
    // 辅助色
    secondary: '#70787D',
    outline: '#E0E0E0',
    
    // 情绪背景光晕 (Aura Colors)
    aura: {
      neutral: ['#F5F5F5', '#E3F2FD'],
      happy: ['#FFF9C4', '#FFE082'],
      sad: ['#E1F5FE', '#B3E5FC'],
      angry: ['#FFEBEE', '#FFCDD2'],
      fearful: ['#F3E5F5', '#E1BEE7'],
      disgusted: ['#F1F8E9', '#DCEDC8'],
      surprised: ['#E0F7FA', '#B2EBF2'],
    },

    text: {
      primary: '#2D3436',   // 极高对比度
      secondary: '#636E72',
      hint: '#B2BEC3',
    }
  },
  typography: {
    fontFamily: 'Lexend_400Regular',
    display: {
      fontSize: 40,
      lineHeight: 48,
      fontWeight: '700',
    },
    headline: {
      fontSize: 28,
      lineHeight: 36,
      fontWeight: '600',
    },
    message: {
      fontSize: 20,         // 减小 2 号，原为 22
      lineHeight: 30,
    },
    label: {
      fontSize: 14,
      letterSpacing: 1.5,
      fontWeight: '600',
    }
  },
  layout: {
    radius: 32,
    spacing: 24,
    innerPadding: 20,
  },
};
