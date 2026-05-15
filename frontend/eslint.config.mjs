/**
 * Minimal ESLint flat config focused on catching the bug class that bit us
 * on iter62: undefined JSX components (missing imports) that pass `react-scripts`
 * webpack-time lint but explode at runtime as a blank screen.
 *
 * NOT a replacement for the CRA dev-mode lint that webpack runs during `yarn
 * start` — this file is for CI / pre-commit / manual `npx eslint src/` runs
 * that the test suite invokes via the `frontend/src/eslint-strict` check.
 *
 * Rules we enforce hard:
 *   - react/jsx-no-undef: if a tag <X /> is used without X in scope, error.
 *     This is exactly what would have caught the HighlightReelsPanel miss.
 *   - no-undef: same idea but for non-JSX identifier references.
 *   - react/jsx-uses-react / react/jsx-uses-vars: required so JSX-only
 *     references don't get flagged as "unused" by no-unused-vars.
 *
 * Everything else is intentionally soft — we don't want this config to
 * become noisy/blocking. The CRA default config still runs in dev for
 * style-level guidance.
 */
import js from '@eslint/js';
import reactPlugin from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

export default [
  // Skip generated / vendor code
  { ignores: ['build/**', 'node_modules/**', 'public/**', 'coverage/**'] },

  // Main rule set for application source
  {
    files: ['src/**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: {
        ...globals.browser,
        ...globals.node,
        process: 'readonly',
      },
    },
    plugins: { react: reactPlugin, 'react-hooks': reactHooks },
    settings: { react: { version: 'detect' } },
    rules: {
      ...js.configs.recommended.rules,

      // The two rules that catch the iter62 bug class
      'react/jsx-no-undef': 'error',
      'no-undef': 'error',

      // Required plumbing so JSX-only references don't get false-flagged
      'react/jsx-uses-react': 'error',
      'react/jsx-uses-vars': 'error',

      // Hooks plugin loaded so eslint-disable-line comments referencing
      // react-hooks/* don't error with "Definition not found".
      'react-hooks/rules-of-hooks': 'off',
      'react-hooks/exhaustive-deps': 'off',

      // Quiet everything that we don't want this strict config to enforce —
      // CRA's webpack lint already covers style-level concerns.
      'no-unused-vars': 'off',  // CRA lint already nags about this in dev
      'no-empty': 'off',
      'no-prototype-builtins': 'off',
      'no-useless-escape': 'off',
      'no-cond-assign': 'off',
      'no-control-regex': 'off',
      'no-misleading-character-class': 'off',
      'no-async-promise-executor': 'off',
      'no-constant-condition': 'off',
      'no-fallthrough': 'off',
    },
  },
];
