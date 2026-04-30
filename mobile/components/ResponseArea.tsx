import React from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { Design } from '../constants/Design';

interface ResponseAreaProps {
  response: string;
}

export const ResponseArea: React.FC<ResponseAreaProps> = ({ response }) => {
  return (
    <View style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.text}>{response}</Text>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    height: 200,
    backgroundColor: Design.colors.surfaceContainerLow,
    margin: Design.layout.spacing,
    borderRadius: Design.layout.roundness,
    padding: 20,
    borderWidth: 1,
    borderColor: Design.colors.primaryContainer,
  },
  content: {
    flexGrow: 1,
  },
  text: {
    fontFamily: Design.typography.fontFamily,
    ...Design.typography.bodyMedium,
    color: Design.colors.primary,
    fontWeight: 'bold',
  },
});
