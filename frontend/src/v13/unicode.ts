/** Convert browser UTF-16 selection offsets to immutable Unicode code points. */
export function codePointRange(text: string, start: number, end: number): [number, number] {
  return [Array.from(text.slice(0,start)).length, Array.from(text.slice(0,end)).length];
}
