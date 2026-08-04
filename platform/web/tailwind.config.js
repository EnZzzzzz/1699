/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive) / <alpha-value>)",
          foreground: "hsl(var(--destructive-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        /* 业务状态色（token 见 src/styles/tokens.css） */
        success: {
          DEFAULT: "hsl(var(--status-success) / <alpha-value>)",
          foreground: "hsl(var(--status-success-foreground) / <alpha-value>)",
        },
        warning: {
          DEFAULT: "hsl(var(--status-warning) / <alpha-value>)",
          foreground: "hsl(var(--status-warning-foreground) / <alpha-value>)",
        },
        info: {
          DEFAULT: "hsl(var(--status-info) / <alpha-value>)",
          foreground: "hsl(var(--status-info-foreground) / <alpha-value>)",
        },
        danger: {
          DEFAULT: "hsl(var(--status-danger) / <alpha-value>)",
          foreground: "hsl(var(--status-danger-foreground) / <alpha-value>)",
        },
        backlog: {
          DEFAULT: "hsl(var(--backlog) / <alpha-value>)",
          foreground: "hsl(var(--backlog-foreground) / <alpha-value>)",
        },
        /* 图表色（recharts 亦可直接 hsl(var(--chart-*))） */
        chart: {
          collected: "hsl(var(--chart-collected) / <alpha-value>)",
          consumed: "hsl(var(--chart-consumed) / <alpha-value>)",
          grid: "hsl(var(--chart-grid) / <alpha-value>)",
          axis: "hsl(var(--chart-axis) / <alpha-value>)",
          "tooltip-bg": "hsl(var(--chart-tooltip-bg) / <alpha-value>)",
          "tooltip-border": "hsl(var(--chart-tooltip-border) / <alpha-value>)",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar-background))",
          foreground: "hsl(var(--sidebar-foreground))",
          primary: "hsl(var(--sidebar-primary))",
          "primary-foreground": "hsl(var(--sidebar-primary-foreground))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
          ring: "hsl(var(--sidebar-ring))",
        },
      },
      spacing: {
        sidebar: "var(--sidebar-width)",
      },
      borderRadius: {
        xl: "calc(var(--radius) + 4px)",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        xs: "calc(var(--radius) - 6px)",
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "caret-blink": {
          "0%,70%,100%": { opacity: "1" },
          "20%,50%": { opacity: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "caret-blink": "caret-blink 1.25s ease-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}