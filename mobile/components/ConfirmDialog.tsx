import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Modal } from 'react-native';
import { Design } from '../constants/Design';

interface ConfirmDialogProps {
  visible: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  visible,
  title,
  message,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}) => {
  if (!visible) return null;

  return (
    <Modal
      transparent
      visible={visible}
      animationType="fade"
      onRequestClose={onCancel}
    >
      <View style={styles.overlay}>
        <View style={styles.dialog}>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.message}>{message}</Text>
          <View style={styles.buttons}>
            <TouchableOpacity
              style={styles.cancelBtn}
              onPress={onCancel}
              accessibilityRole="button"
              accessibilityLabel={cancelLabel}
            >
              <Text style={styles.cancelText}>{cancelLabel}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.confirmBtn}
              onPress={onConfirm}
              accessibilityRole="button"
              accessibilityLabel={confirmLabel}
            >
              <Text style={styles.confirmText}>{confirmLabel}</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.25)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 40,
  },
  dialog: {
    backgroundColor: Design.colors.surface,
    borderRadius: Design.layout.radius,
    padding: 28,
    maxWidth: 340,
    width: '100%',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.12,
    shadowRadius: 24,
    elevation: 10,
  },
  title: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 20,
    fontWeight: '600',
    color: Design.colors.text.primary,
    marginBottom: 8,
  },
  message: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 16,
    lineHeight: 24,
    color: Design.colors.text.secondary,
    marginBottom: 24,
  },
  buttons: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 12,
  },
  cancelBtn: {
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: Design.layout.radiusSmall,
    backgroundColor: Design.colors.surfaceDim,
  },
  cancelText: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 16,
    color: Design.colors.text.secondary,
    fontWeight: '500',
  },
  confirmBtn: {
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: Design.layout.radiusSmall,
    backgroundColor: Design.colors.primary,
  },
  confirmText: {
    fontFamily: Design.typography.fontFamily,
    fontSize: 16,
    color: Design.colors.onPrimary,
    fontWeight: '600',
  },
});
