/** Recommender source label (Song.why, as sent by the backend) → small icon. The full label stays in the
 *  tooltip and in the song menu, so rows show one glyph instead of a text pill. */
const ICON: Record<string, string> = {
  'similar': 'radio',
  'your taste': 'taste',
  'recommended for you': 'spark',
  'sounds like you': 'wave',
  'you liked this': 'history',
  'new for you': 'compass',
  'matches the vibe': 'wave',
  'from your Spotify years': 'history',
}
export const whyIcon = (why?: string) => (why ? ICON[why] ?? 'spark' : '')
