import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // AWS brand colors
        aws: {
          orange: "#FF9900",
          "orange-dark": "#E07B00",
          "squid-ink": "#232F3E",
          "smile-blue": "#146EB4",
          "light-blue": "#1A9ED9",
        },
        // Discord brand
        discord: {
          blurple: "#5865F2",
          green: "#57F287",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
