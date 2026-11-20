/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#FAF9F5",
        sidebar: "#F5F4EE",
        ink: "#141413",
        muted: "#73726C",
        line: "#E6E4DB",
        hover: "#EFEEE7",
        ok: "#2F7D4F",
      },
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', 'sans-serif'],
        serif: ['ui-serif', 'Georgia', 'Cambria', '"Times New Roman"', 'serif'],
      },
      keyframes: {
        pop: { from: { opacity: "0", transform: "scale(.97)" }, to: { opacity: "1", transform: "scale(1)" } },
        fade: { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: { pop: "pop .15s ease-out", fade: "fade .15s ease-out" },
    },
  },
  plugins: [],
};
