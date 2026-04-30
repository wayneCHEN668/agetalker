name: Companion Design System
colors:
  surface: '#f4faff'
  surface-dim: '#c0dfee'
  surface-bright: '#f4faff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#e6f6ff'
  surface-container: '#d9f0fc'
  surface-container-high: '#cceaf9'
  surface-container-highest: '#bfe4f6'
  on-surface: '#001e2c'
  on-surface-variant: '#40484c'
  outline: '#70787d'
  outline-variant: '#c0c8cc'
  primary: '#00668a'
  on-primary: '#ffffff'
  primary-container: '#c3e8ff'
  on-primary-container: '#001e2c'
  secondary: '#4e616c'
  on-secondary: '#ffffff'
  secondary-container: '#d1e5f2'
  on-secondary-container: '#0a1e28'
  tertiary: '#5f5a7d'
  on-tertiary: '#ffffff'
  tertiary-container: '#e5deff'
  on-tertiary-container: '#1b1736'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#410002'
  happy-bg: '#FFD54F'
  tired-bg: '#E3F2FD'

typography:
  font-family: 'Lexend, sans-serif'
  display-large:
    size: 57px
    weight: 400
    line-height: 64px
  display-medium:
    size: 45px
    weight: 400
    line-height: 52px
  display-small:
    size: 36px
    weight: 400
    line-height: 44px
  headline-large:
    size: 32px
    weight: 400
    line-height: 40px
  headline-medium:
    size: 28px
    weight: 400
    line-height: 36px
  headline-small:
    size: 24px
    weight: 400
    line-height: 32px
  body-large:
    size: 20px
    weight: 400
    line-height: 28px
  body-medium:
    size: 18px
    weight: 400
    line-height: 24px

layout:
  roundness: 32px
  spacing: 24px

---

# 对话伴侣设计系统 (Companion Design System)

这是为老年人设计的“对话伴侣”应用的核心设计指南。该系统专注于高对比度、大字体和直观的情感色彩反馈。

## 设计原则

1. **易读性第一**：采用 Lexend 字体，并显著增大字号，确保视力受损的老年人也能清晰阅读。
2. **直观反馈**：通过背景颜色的温柔渐变（如快乐状态的暖黄，疲惫状态的浅蓝）提供即时的情感反馈。
3. **极简交互**：移除复杂的导航，强化单一的核心操作（如巨大的“挂断”按钮）。
4. **视觉辅助**：利用动态声波图提供“正在聆听”和“正在说话”的视觉确认。

## 核心组件说明

### 状态栏 (Status Bar)
- **位置**：屏幕顶部。
- **功能**：通过文字（“正在聆听...”、“正在说话...”）配合呼吸动效图标提示当前状态。

### 文本展示区 (Text Areas)
- **转录文本**：显示用户说话的实时转录，句子逐个追加，并配有情绪小角标。
- **回复文本**：采用气泡样式，字体加粗，模拟对话感。

### 声波动画 (Waveform)
- **视觉**：双层线段设计。
- **待机**：缓慢起伏。
- **通话中**：随音量实时波动。

### 挂断按钮 (Hang Up Button)
- **颜色**：醒目的红色 (`error`)。
- **样式**：长条或圆形大按钮，带电话挂断图标，易于识别和点击。