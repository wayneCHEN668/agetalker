import React from 'react';
import { Link, Tabs } from 'expo-router';
import { Pressable, Text } from 'react-native';

import Colors from '@/constants/Colors';
import { useColorScheme } from '@/components/useColorScheme';
import { useClientOnlyValue } from '@/components/useClientOnlyValue';
import { Design } from '@/constants/Design';

export default function TabLayout() {
  const colorScheme = useColorScheme();

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: Colors[colorScheme ?? 'light'].tint,
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
          height: 50,
        },
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: '聊聊天',
          tabBarIcon: ({ color }) => (
            <Text style={{ fontSize: 24, color }}>💬</Text>
          ),
          headerRight: () => (
            <Link href="/modal" asChild>
              <Pressable>
                {({ pressed }) => (
                  <Text
                    style={{
                      fontFamily: Design.typography.fontFamily,
                      fontSize: 15,
                      color: Colors[colorScheme ?? 'light'].text,
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
          title: '玩游戏',
          tabBarIcon: ({ color }) => (
            <Text style={{ fontSize: 24, color }}>🎮</Text>
          ),
        }}
      />
    </Tabs>
  );
}
