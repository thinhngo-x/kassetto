// What a track's end says about it: the skip rules, kept pure so they can be tested (outcome.test.ts).

export type EndEvent = 'complete' | 'partial' | 'skip'
export type EndReason = 'ended' | 'next' | 'switch' | 'error'

/** complete = it ended or >= 80 % was heard; skip = left early (< 30 s and < 25 % of it); else partial. */
export function endEvent(pos: number, dur: number, ended = false): EndEvent {
  if (ended || (dur && pos >= 0.8 * dur)) return 'complete'
  return pos < Math.min(30, dur * 0.25) ? 'skip' : 'partial'
}

/** Only a real choice counts against a song (null = report nothing):
 *  - 'next' (next button / media key) early = skip (the player still waits 20 s before sending it: a mis-tap
 *    can be undone by going back);
 *  - 'switch' (picked another song / list) early = nothing: you changed your mind, you didn't reject this one;
 *  - 'error' (couldn't play) or a song that never became audible (still loading) = nothing. */
export function trackOutcome(reason: EndReason, pos: number, dur: number, audible: boolean): EndEvent | null {
  if (reason === 'error' || !audible) return null
  const ev = endEvent(pos, dur, reason === 'ended')
  return ev === 'skip' && reason === 'switch' ? null : ev
}

/** On the speaker: the same rules from polled positions; a stop (speaker / app / back to the phone) isn't a skip. */
export function speakerOutcome(pos: number, dur: number, stopped: boolean): EndEvent | null {
  if (!dur || pos < 1) return null
  const ev = endEvent(pos, dur, dur - pos < 4)
  return ev === 'skip' && stopped ? null : ev
}
