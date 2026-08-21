import React from 'react';
import { Link, Tabs } from 'expo-router';
import { Pressable, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useClientOnlyValue } from '@/components/useClientOnlyValue';
import { Design } from '@/constants/Design';

export default function TabLayout() {
  const insets = useSafeAreaInsets();

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: Design.colors.primary,
        headerShown: useClientOnlyValue(false, true),
        tabBarLabelStyle: {
          fontSize: 16,
          fontFamily: 'Lexend_400Regular',
        },
        tabBarStyle: {
          height: 72,
          paddingBottom: 8,
        },
        headerTitleStyle: {
          fontSize: 16,
          fontFamily: 'Lexend_400Regular',
        },
        headerStyle: {
          height: 50 + insets.top,
        },
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: '聊聊天',
          tabBarIcon: () => null,
          headerRight: () => (
            <Link href="/modal" asChild>
              <Pressable>
                {({ pressed }) => (
                  <Text
                    style={{
                      fontFamily: Design.typography.fontFamily,
                      fontSize: 15,
                      color: Design.colors.text.primary,
                      marginRight: 15,
                      opacity: pressed ? 0.5 : 1,
                    }}>
                    关于
                  </Text>
                )}
              </Pressable>
            </Link>
          ),
        }}
      />
      <Tabs.Screen
        name="two"
        options={{
          title: '练练脑',
          tabBarIcon: () => null,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: '我自己',
          tabBarIcon: () => null,
        }}
      />
    </Tabs>
  );
}
