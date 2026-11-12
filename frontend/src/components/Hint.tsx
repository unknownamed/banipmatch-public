// 제목 옆 ⓘ: 설명문을 화면에 늘어놓지 않고, 필요할 때만 마우스 올림(PC)·누름(휴대폰)으로 보여 준다.
export function Hint({ text }: { text: string }) {
  return (
    <span className="hint" tabIndex={0} role="note" aria-label={text}>
      <span aria-hidden="true">ⓘ</span>
      <span className="hint-pop" aria-hidden="true">{text}</span>
    </span>
  )
}
