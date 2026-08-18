module.exports = {
  preset: 'jest-expo',
  moduleNameMapper: {
    // tsconfig.json 里 "@/*" -> "./*"。jest 不读 tsconfig paths，必须在这里重复一遍。
    '^@/(.*)$': '<rootDir>/$1',
  },
  transformIgnorePatterns: [
    'node_modules/(?!((jest-)?react-native|@react-native(-community)?|expo(nent)?|@expo(nent)?/.*|@expo-google-fonts/.*|react-navigation|@react-navigation/.*|@testing-library/react-native))',
  ],
};
