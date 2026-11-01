export interface Segment {
  text: string;
  match: boolean;
}

/**
 * Splits `text` into plain and matching segments for every search term,
 * case-insensitively. Plain string matching on purpose: user input never
 * becomes a regular expression.
 */
export function highlightSegments(text: string, query: string | undefined): Segment[] {
  const terms = (query ?? '').toLowerCase().split(/\s+/).filter(Boolean);
  const lower = text.toLowerCase();
  // Lower-casing can change the length of some characters; then indices would not line up.
  if (!terms.length || lower.length !== text.length) return [{ text, match: false }];

  const segments: Segment[] = [];
  let start = 0;
  while (start < text.length) {
    let next = -1;
    let length = 0;
    for (const term of terms) {
      const index = lower.indexOf(term, start);
      if (index !== -1 && (next === -1 || index < next || (index === next && term.length > length))) {
        next = index;
        length = term.length;
      }
    }
    if (next === -1) break;
    if (next > start) segments.push({ text: text.slice(start, next), match: false });
    segments.push({ text: text.slice(next, next + length), match: true });
    start = next + length;
  }
  if (start < text.length) segments.push({ text: text.slice(start), match: false });
  return segments;
}
