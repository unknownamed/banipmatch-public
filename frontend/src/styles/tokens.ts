export const tokens = {
  color: {
    primary: '#211922',
    primaryHover: '#433a44',
    bg: '#ffffff',
    text: '#211922',
    secondary: '#e5e5e0',
    accent: '#2b48d4',
    neutral: { 300: '#91918c', 500: '#62625b', 700: '#474742' },
    danger: '#d1001f',
    success: '#1f7a4d',
  },
  font: {
    sans: "'Pretendard', system-ui, 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif",
    size: { 12: '12px', 14: '14px', 16: '16px', 20: '20px', 28: '28px' },
    weight: { medium: 500, bold: 700 },
  },
  space: { 1: '4px', 2: '8px', 3: '12px', 4: '16px', 6: '24px', 8: '32px', 12: '48px' },
  radius: { sm: '8px', md: '12px', lg: '16px', xl: '24px', pill: '999px' },
  duration: { fast: '85ms', base: '200ms' },
} as const
export type Tokens = typeof tokens
