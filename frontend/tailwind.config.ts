import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
    "./store/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        "glass-white": "rgba(255,255,255,0.08)",
        "glass-border": "rgba(255,255,255,0.12)",
        "glass-hover": "rgba(255,255,255,0.12)",
        accent: "#6366f1",
        "accent-glow": "rgba(99,102,241,0.3)",
      },
    },
  },
  plugins: [],
};

export default config;
