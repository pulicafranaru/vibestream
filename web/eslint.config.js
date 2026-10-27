import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'

// Deliberately narrow: catches undeclared names (a blank screen on the TV), not style.
export default [
  {
    files: ['src/**/*.{js,jsx}'],
    plugins: { react, 'react-hooks': reactHooks },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    settings: { react: { version: 'detect' } },
    rules: {
      ...js.configs.recommended.rules,
      'no-undef': 'error',
      'react/jsx-uses-vars': 'error',
      'react/jsx-uses-react': 'error',
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^(_|React)' }],
      'no-empty': ['warn', { allowEmptyCatch: true }],
      'react-hooks/rules-of-hooks': 'error',
    },
  },
]
