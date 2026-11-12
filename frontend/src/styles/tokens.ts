export const tokens = {
  color: {
    bg: '#ffffff',
    canvas: '#fafafa',
    text: '#141414',
    muted: '#6f6d6e',
    line: '#ececec',
    hover: '#f4f4f4',
    accent: '#16294D',
    accentStrong: '#16294D',
    danger: '#b0365c',
    success: '#237a4b',
    lock: '#2a6f8c',
  },
  font: {
    sans: "'Pretendard', system-ui, 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif",
    size: { 12: '12px', 13: '13px', 14: '14px', 16: '16px', 20: '20px', 30: '30px' },
    weight: { medium: 500, bold: 600 },
  },
  space: { 1: '4px', 2: '8px', 3: '12px', 4: '16px', 5: '20px', 6: '24px', 8: '32px' },
  radius: { sm: '6px', md: '8px', lg: '12px', pill: '999px' },
  duration: { fast: '85ms', base: '200ms' },
} as const
export type Tokens = typeof tokens
