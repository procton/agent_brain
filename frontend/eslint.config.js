import eslint from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      eslint.configs.recommended,
      // @ts-ignore - typing of eslint-config helper arrays
      ...tseslint.configs.recommended,
    ],
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      ...reactHooks.configs["recommended-latest"].rules,
      "no-console": ["warn", { allow: ["error"] }],
      eqeqeq: ["error", "smart"],
    },
  },
  {
    ignores: ["node_modules/**", "dist/**", "coverage/**"],
  }
);
