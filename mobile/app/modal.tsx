import { StatusBar } from 'expo-status-bar';
import type { ReactNode } from 'react';
import { Platform, ScrollView, StyleSheet } from 'react-native';

import { Text, View } from '@/components/Themed';
import { Design } from '@/constants/Design';

/**
 * 关于页面：介绍 App 的功能，以及数据安全相关的说明。
 *
 * 面向老年用户，所以措辞尽量口语化、避免专业术语；数据安全部分只写
 * 实际存在的机制，不做无法兑现的承诺（比如不写"完全离线""绝不上传"这种
 * 与云端 ASR/LLM/TTS 架构相悖的说法）。
 */
export default function ModalScreen() {
  return (
    <View style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}>
        <Text style={styles.appName}>蘅小年</Text>
        <Text style={styles.tagline}>陪您说说话的语音伙伴</Text>

        <Section title="这是做什么用的">
          <Paragraph>
            蘅小年是一款给老人用的语音聊天伙伴。您对着它说话，它会听懂您说的内容，
            体会您话里的情绪，然后用温和的语气回应您、陪您聊聊天。
          </Paragraph>
          <Paragraph>
            蘅小年会记得您之前聊过的事情，下次再聊起来，不用每次都从头介绍自己。
          </Paragraph>
          <Paragraph>
            如果蘅小年察觉到您可能正处在比较危险的情绪状态里，会换一种更谨慎的方式
            回应您，并且提醒身边的护理人员来看看您。
          </Paragraph>
        </Section>

        <Section title="您的数据是怎么处理的">
          <Paragraph>
            您说的话会被转换成文字，用来听懂您在说什么、理解您的情绪，并生成回复
            念给您听。这个过程中，语音和文字会经过云端的语音识别、语言理解和语音
            合成服务——这是蘅小年能听懂话、会说话的基础，不会用于聊天以外的用途，
            比如不会用来给您推送广告。
          </Paragraph>
          <Paragraph>
            蘅小年记住的关于您的事情（比如您提过的家人、爱好），保存在这个 App
            连接的服务器上，只在您和蘅小年聊天时用来帮您接话，不会分享给聊天服务
            提供商以外的第三方。
          </Paragraph>
          <Paragraph>
            如果聊天中出现让人担心的情况，蘅小年会记一条提醒，让护理人员能及时
            知道、上门看看您，这是为了您的安全。
          </Paragraph>
          <Paragraph style={styles.hint}>
            如果您想了解更多，或者希望删除蘅小年记住的内容，可以请身边的工作人员
            帮忙联系我们。
          </Paragraph>
        </Section>

        <Text style={styles.version}>版本 1.0.0</Text>
      </ScrollView>

      <StatusBar style={Platform.OS === 'ios' ? 'light' : 'auto'} />
    </View>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Paragraph({ children, style }: { children: ReactNode; style?: object }) {
  return <Text style={[styles.paragraph, style]}>{children}</Text>;
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: Design.layout.innerPadding,
    paddingTop: 32,
    paddingBottom: 48,
  },
  appName: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.display.fontSize,
    lineHeight: Design.typography.display.lineHeight,
    fontWeight: Design.typography.display.fontWeight,
    color: Design.colors.primary,
    textAlign: 'center',
  },
  tagline: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.caption.fontSize,
    color: Design.colors.text.secondary,
    textAlign: 'center',
    marginTop: 4,
    marginBottom: Design.layout.spacing,
  },
  section: {
    marginBottom: Design.layout.spacing,
    backgroundColor: Design.colors.surface,
    borderRadius: Design.layout.radius,
    padding: Design.layout.innerPadding,
  },
  sectionTitle: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.headline.fontSize,
    lineHeight: Design.typography.headline.lineHeight,
    fontWeight: Design.typography.headline.fontWeight,
    color: Design.colors.text.primary,
    marginBottom: 12,
  },
  paragraph: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.message.fontSize,
    lineHeight: Design.typography.message.lineHeight,
    color: Design.colors.text.primary,
    marginBottom: 12,
  },
  hint: {
    color: Design.colors.text.secondary,
    marginBottom: 0,
  },
  version: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.caption.fontSize,
    color: Design.colors.text.hint,
    textAlign: 'center',
    marginTop: 8,
  },
});
