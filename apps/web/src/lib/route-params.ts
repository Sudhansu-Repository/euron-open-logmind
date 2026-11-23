/** Route params arrive decoded in the App Router; decode again only if something is still escaped, and never throw. */
export function decodeParam(value: string): string {
  try {
    return /%[0-9A-Fa-f]{2}/.test(value) ? decodeURIComponent(value) : value;
  } catch {
    return value;
  }
}
