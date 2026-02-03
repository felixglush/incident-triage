/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        obsidian: "#0b0f14",
        graphite: "#121924",
        slate: "#1b2431",
        mist: "#c8d0d8",
        accent: "#f5c84c",
        critical: "#f25c5c",
        warning: "#f0a14a",
        info: "#59c2ff",
        success: "#4cc38a"
      },
      fontFamily: {
        display: ["'Fraunces'", "serif"],
        body: ["'Space Grotesk'", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"]
      },
      boxShadow: {
        glow: "0 0 30px rgba(89, 194, 255, 0.25)",
        soft: "0 12px 40px rgba(8, 12, 18, 0.35)"
      },
      borderRadius: {
        xl2: "1.25rem"
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-6px)" }
        },
        pulseGlow: {
          "0%, 100%": { boxShadow: "0 0 0 rgba(242, 92, 92, 0.0)" },
          "50%": { boxShadow: "0 0 24px rgba(242, 92, 92, 0.35)" }
        }
      },
      animation: {
        float: "float 6s ease-in-out infinite",
        pulseGlow: "pulseGlow 2.8s ease-in-out infinite"
      }
    }
  },
  plugins: []
};
