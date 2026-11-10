export const tokens = {
  color: {
    bg: '#ffffff',
    canvas: '#f4f7fb',
    text: '#1f2329',
    muted: '#555555',
    line: '#dddddd',
    hover: '#f6faff',
    navy: '#1b2750',
    navyDeep: '#00164d',
    primarySoft: '#d4eaff',
    blue: '#006edb',
    blueStrong: '#1e429b',
    danger: '#c62f2f',
    success: '#2f7d12',
  },
  font: {
    sans: "'Noto Sans KR', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif",
    size: { 12: '12px', 13: '13px', 14: '14px', 15: '15px', 20: '20px', 27: '27px' },
    weight: { medium: 500, bold: 700 },
  },
  space: { 1: '4px', 2: '8px', 3: '12px', 4: '16px', 5: '20px', 6: '24px', 8: '32px' },
  radius: { sm: '4px', md: '7px', lg: '8px', pill: '50px' },
  duration: { fast: '85ms', base: '300ms' },
} as const
export type Tokens = typeof tokens
