const nextConfig = require('eslint-config-next');
const prettierConfig = require('eslint-config-prettier');
const prettierPlugin = require('eslint-plugin-prettier');

/** @type {import('eslint').Linter.Config[]} */
module.exports = [
  // Next.js recommended rules (flat config array)
  ...nextConfig,
  // Prettier: disable conflicting formatting rules
  {
    rules: prettierConfig.rules,
  },
  // Prettier: enforce formatting as lint errors
  {
    plugins: {
      prettier: prettierPlugin,
    },
    rules: {
      'prettier/prettier': 'warn',
    },
  },
];
