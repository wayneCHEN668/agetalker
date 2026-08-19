/**
 * 「我自己」—— 系统需要了解的基础信息，老人自己看、自己改。
 *
 * 只列 13 个 askable 字段（后端 /profile 已经筛过）：紧急联系人、药名、房间号
 * 是护理员录的；话多话少、情绪底色是系统从对话行为统计出来的，手改下一轮就被
 * 盖掉。这一页不显示它们。
 *
 * 给老人用的三条取舍：
 * 1. 一行一个字段，行高够大（>=72），手抖也点得中；
 * 2. 没填的写「还没说」而不是留白——留白看起来像坏了；
 * 3. 编辑用整屏的浮层，不是行内输入框。行内输入框在小屏上会被键盘顶掉，
 *    老人看不见自己在改哪一栏。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  StyleSheet, View, Text, ScrollView, TouchableOpacity, TextInput,
  Modal, ActivityIndicator, KeyboardAvoidingView, Platform,
} from 'react-native';

import { Design } from '@/constants/Design';
import { getElderId } from '@/constants/Session';
import { API_BASE_URL } from '@/constants/Api';

const API_BASE = API_BASE_URL;

interface Slot {
  name: string;
  zh: string;
  value: string;
  status: string;
}

/** 岁数那一栏对老人显示的是「岁数」，但后端存的是出生年份，两种输入都收。 */
const HINTS: Record<string, string> = {
  birth_year: '填岁数或者出生年份都行，比如 83 或者 1943',
};

export default function ProfileScreen() {
  const [slots, setSlots] = useState<Slot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 正在编辑的那一栏。null 表示浮层没开。
  const [editing, setEditing] = useState<Slot | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  // 缓存 Promise 本身而不是 resolve 后的值，与 useLLM 里同一个理由：原生端
  // getElderId() 走 AsyncStorage，读取没回来之前不能把默认值发出去。
  const elderIdPromiseRef = useRef<Promise<string> | null>(null);
  if (elderIdPromiseRef.current === null) {
    elderIdPromiseRef.current = getElderId();
  }

  const load = useCallback(async () => {
    try {
      const elderId = await elderIdPromiseRef.current!;
      const res = await fetch(
        `${API_BASE}/profile?elder_id=${encodeURIComponent(elderId)}`,
      );
      const data = await res.json();
      setSlots(data.slots || []);
      setError(data.enabled === false ? '这项功能现在没开着。' : '');
    } catch {
      setError('没能读到您的资料，等会儿再试试。');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openEditor = (slot: Slot) => {
    setEditing(slot);
    setDraft(slot.value);
  };

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/profile/slot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          elder_id: await elderIdPromiseRef.current!,
          name: editing.name,
          value: draft,
        }),
      });
      const data = await res.json();
      if (!data.ok) {
        // 目前唯一会被拒的是岁数填得不成样子。别把老人关在浮层里，
        // 说清楚哪儿不对，让他改。
        setError(
          editing.name === 'birth_year'
            ? '这个岁数看着不太对，您再看看？'
            : '这条没能存上。',
        );
        return;
      }
      setSlots((prev) =>
        prev.map((s) => (s.name === data.slot.name ? data.slot : s)),
      );
      setError('');
      setEditing(null);
    } catch {
      setError('没存上，等会儿再试试。');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <View style={[styles.container, styles.centered]}>
        <ActivityIndicator size="large" color={Design.colors.primary} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <ScrollView contentContainerStyle={styles.list}>
        <Text style={styles.intro}>
          这些是我想知道的事。您愿意说的，点一下就能改。
        </Text>

        {error !== '' && <Text style={styles.error}>{error}</Text>}

        {slots.map((slot) => (
          <TouchableOpacity
            key={slot.name}
            style={styles.row}
            onPress={() => openEditor(slot)}
            accessibilityRole="button"
            accessibilityLabel={`${slot.zh}，${slot.value || '还没说'}，点一下修改`}
          >
            <Text style={styles.rowLabel}>{slot.zh}</Text>
            <Text style={slot.value ? styles.rowValue : styles.rowEmpty}>
              {slot.value || '还没说'}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <Modal
        visible={editing !== null}
        animationType="slide"
        transparent
        onRequestClose={() => setEditing(null)}
      >
        <KeyboardAvoidingView
          style={styles.sheetBackdrop}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        >
          <View style={styles.sheet}>
            <Text style={styles.sheetTitle}>{editing?.zh}</Text>
            {editing && HINTS[editing.name] && (
              <Text style={styles.sheetHint}>{HINTS[editing.name]}</Text>
            )}

            <TextInput
              style={styles.input}
              value={draft}
              onChangeText={setDraft}
              placeholder="还没说"
              placeholderTextColor={Design.colors.text.hint}
              autoFocus
              keyboardType={editing?.name === 'birth_year' ? 'number-pad' : 'default'}
            />

            {/* 清空要单独给一个口子：留着一个改不掉的错值比空着更糟，
                而清空之后 AI 会重新问，等于把这一栏交还给对话去采。 */}
            <TouchableOpacity
              style={styles.clearButton}
              onPress={() => setDraft('')}
              accessibilityRole="button"
            >
              <Text style={styles.clearText}>清空这一栏</Text>
            </TouchableOpacity>

            <View style={styles.sheetActions}>
              <TouchableOpacity
                style={[styles.button, styles.buttonGhost]}
                onPress={() => setEditing(null)}
                disabled={saving}
                accessibilityRole="button"
              >
                <Text style={styles.buttonGhostText}>不改了</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.button, styles.buttonPrimary]}
                onPress={save}
                disabled={saving}
                accessibilityRole="button"
              >
                <Text style={styles.buttonPrimaryText}>
                  {saving ? '存着…' : '存下'}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Design.colors.background,
  },
  centered: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  list: {
    padding: Design.layout.innerPadding,
    paddingBottom: 40,
  },
  intro: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.message.fontSize,
    lineHeight: Design.typography.message.lineHeight,
    color: Design.colors.text.secondary,
    marginBottom: 20,
  },
  error: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 16,
    color: Design.colors.crisis,
    marginBottom: 16,
  },
  row: {
    minHeight: 72,
    backgroundColor: Design.colors.surface,
    borderRadius: Design.layout.radiusSmall,
    borderWidth: 1,
    borderColor: Design.colors.outline,
    paddingHorizontal: 18,
    paddingVertical: 14,
    marginBottom: 12,
    justifyContent: 'center',
  },
  rowLabel: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 15,
    color: Design.colors.text.hint,
    marginBottom: 4,
  },
  rowValue: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 22,
    lineHeight: 30,
    color: Design.colors.text.primary,
  },
  rowEmpty: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 22,
    lineHeight: 30,
    color: Design.colors.text.hint,
  },
  sheetBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(45, 35, 32, 0.45)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: Design.colors.surface,
    borderTopLeftRadius: Design.layout.radius,
    borderTopRightRadius: Design.layout.radius,
    padding: Design.layout.spacing,
    paddingBottom: 36,
  },
  sheetTitle: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.headline.fontSize,
    fontWeight: Design.typography.headline.fontWeight,
    color: Design.colors.text.primary,
    marginBottom: 6,
  },
  sheetHint: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 15,
    color: Design.colors.text.hint,
    marginBottom: 12,
  },
  input: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 24,
    color: Design.colors.text.primary,
    backgroundColor: Design.colors.surfaceDim,
    borderRadius: Design.layout.radiusSmall,
    paddingHorizontal: 16,
    paddingVertical: 16,
    marginTop: 8,
  },
  clearButton: {
    alignSelf: 'flex-start',
    paddingVertical: 12,
  },
  clearText: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 16,
    color: Design.colors.secondary,
    textDecorationLine: 'underline',
  },
  sheetActions: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 8,
  },
  button: {
    flex: 1,
    paddingVertical: 16,
    borderRadius: Design.layout.radiusSmall,
    alignItems: 'center',
  },
  buttonGhost: {
    backgroundColor: Design.colors.surfaceDim,
  },
  buttonGhostText: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 18,
    color: Design.colors.text.secondary,
  },
  buttonPrimary: {
    backgroundColor: Design.colors.primary,
  },
  buttonPrimaryText: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 18,
    fontWeight: '600',
    color: Design.colors.onPrimary,
  },
});
