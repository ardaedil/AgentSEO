import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {extend: {colors: {ink: "#101828", paper: "#f7f8fa", accent: "#5b5bd6", mint: "#14b87a"}}},
  plugins: [],
} satisfies Config;

