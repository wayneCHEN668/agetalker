import { Link, Stack } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';

import { Design } from '@/constants/Design';

export default function NotFoundScreen() {
  return (
    <>
      <Stack.Screen options={{ title: '走丢了' }} />
      <View style={styles.container}>
        <Text style={styles.title}>这个页面不存在</Text>
        <Text style={styles.hint}>可能是链接不对，回到聊天页看看吧。</Text>

        <Link href="/" style={styles.link}>
          <Text style={styles.linkText}>回到聊聊天</Text>
        </Link>
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: Design.layout.spacing,
    backgroundColor: Design.colors.background,
  },
  title: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.headline.fontSize,
    lineHeight: Design.typography.headline.lineHeight,
    fontWeight: Design.typography.headline.fontWeight,
    color: Design.colors.text.primary,
    textAlign: 'center',
  },
  hint: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.message.fontSize,
    lineHeight: Design.typography.message.lineHeight,
    color: Design.colors.text.secondary,
    textAlign: 'center',
    marginTop: 8,
  },
  link: {
    marginTop: Design.layout.spacing,
    paddingHorizontal: 24,
    paddingVertical: 14,
    borderRadius: 26,
    backgroundColor: Design.colors.primary,
  },
  linkText: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 16,
    fontWeight: '600',
    color: Design.colors.onPrimary,
  },
});
