/** The chip tones the design system defines (components/ui/chip.tsx, globals.css). */
export const TONES = [
  "success",
  "info",
  "primary",
  "warning",
  "danger",
  "neutral",
  "orange",
  "fuchsia",
  "cyan",
] as const;
export type Tone = (typeof TONES)[number];

export interface Spec {
  label: string;
  tone: Tone;
  hint?: string;
}
