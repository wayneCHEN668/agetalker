import React from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { Design } from '../constants/Design';

interface ResponseAreaProps {
  response: string;
  strategyName?: string;
}

export const ResponseArea: React.FC<ResponseAreaProps> = ({ response, strategyName }) => {
  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.label}>智慧伙伴</Text>
        {strategyName ? (
          <View style={styles.strategyBadge}>
            <Text style={styles.strategyText}>{strategyName}</Text>
          </View>
        ) : null}
      </View>
      <ScrollView 
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <Text style={styles.text}>{response}</Text>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    height: 220,
    backgroundColor: Design.colors.surface,
    marginHorizontal: Design.layout.spacing,
    marginBottom: 40,
    borderRadius: Design.layout.radius,
    padding: Design.layout.innerPadding,
    // Soft premium shadow
    shadowColor: Design.colors.primary,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.1,
    shadowRadius: 20,
    elevation: 8,
    borderWidth: 1,
    borderColor: 'rgba(74, 103, 65, 0.1)',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  label: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.label.fontSize,
    color: Design.colors.text.hint,
    fontWeight: '700',
    letterSpacing: 2,
  },
  strategyBadge: {
    backgroundColor: 'rgba(74, 103, 65, 0.08)',
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 8,
    borderWidth: 0.5,
    borderColor: 'rgba(74, 103, 65, 0.2)',
  },
  strategyText: {
    fontSize: 12,
    color: Design.colors.primary,
    fontWeight: '600',
  },
  content: {
    flexGrow: 1,
    justifyContent: 'center',
  },
  text: {
    fontFamily: Design.typography.fontFamily,
    fontSize: Design.typography.message.fontSize,
    lineHeight: Design.typography.message.lineHeight,
    color: Design.colors.primary,
    textAlign: 'center',
    fontWeight: '500',
  },
});
