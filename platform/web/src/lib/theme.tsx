import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'

/** 主题模式：light 亮色 / dark 暗色 / system 跟随系统 */
export type Theme = 'light' | 'dark' | 'system'
/** 实际生效的主题（system 会被解析为 light 或 dark） */
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'platform-theme'
const MEDIA_QUERY = '(prefers-color-scheme: dark)'

interface ThemeContextValue {
  /** 用户选择的主题模式 */
  theme: Theme
  /** 解析后的实际主题 */
  resolvedTheme: ResolvedTheme
  setTheme: (theme: Theme) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined' || !window.matchMedia) return 'dark'
  return window.matchMedia(MEDIA_QUERY).matches ? 'dark' : 'light'
}

function readStoredTheme(fallback: Theme): Theme {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    // localStorage 不可用时静默回退
  }
  return fallback
}

export function ThemeProvider({
  children,
  defaultTheme = 'dark',
}: {
  children: ReactNode
  defaultTheme?: Theme
}) {
  const [theme, setThemeState] = useState<Theme>(() => readStoredTheme(defaultTheme))
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(getSystemTheme)

  // system 模式：监听系统配色变化
  useEffect(() => {
    const mq = window.matchMedia(MEDIA_QUERY)
    const onChange = (e: MediaQueryListEvent) => {
      setSystemTheme(e.matches ? 'dark' : 'light')
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const resolvedTheme: ResolvedTheme = theme === 'system' ? systemTheme : theme

  // 在 <html> 上切换 .dark class（tailwind darkMode: ["class"] 约定）
  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', resolvedTheme === 'dark')
    root.style.colorScheme = resolvedTheme
  }, [resolvedTheme])

  const setTheme = (next: Theme) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // localStorage 不可用时仅内存生效
    }
    setThemeState(next)
  }

  return (
    <ThemeContext.Provider value={{ theme, resolvedTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme 必须在 <ThemeProvider> 内使用')
  return ctx
}
