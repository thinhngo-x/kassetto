import { describe, expect, it } from 'vitest'
import { endEvent, speakerOutcome, trackOutcome } from './outcome'

describe('endEvent', () => {
  it('counts a song as finished when it ended or 80 % was heard', () => {
    expect(endEvent(10, 200, true)).toBe('complete')
    expect(endEvent(160, 200)).toBe('complete')
    expect(endEvent(159, 200)).toBe('partial')
  })
  it('a skip is under 30 s and under a quarter of the song', () => {
    expect(endEvent(29, 200)).toBe('skip')
    expect(endEvent(30, 200)).toBe('partial')
    expect(endEvent(20, 60)).toBe('partial')          // a third of a short song is not a skip
    expect(endEvent(14, 60)).toBe('skip')
  })
  it('unknown duration is never a skip', () => {
    expect(endEvent(3, 0)).toBe('partial')
  })
})

describe('trackOutcome (phone)', () => {
  it('next pressed early is a skip', () => expect(trackOutcome('next', 5, 200, true)).toBe('skip'))
  it('switching to something else early is nothing', () => expect(trackOutcome('switch', 5, 200, true)).toBeNull())
  it('switching after hearing most of it still counts', () => {
    expect(trackOutcome('switch', 120, 200, true)).toBe('partial')
    expect(trackOutcome('switch', 190, 200, true)).toBe('complete')
  })
  it('errors and songs that never started are nothing', () => {
    expect(trackOutcome('error', 5, 200, true)).toBeNull()
    expect(trackOutcome('next', 0, 200, false)).toBeNull()
  })
})

describe('speakerOutcome (Cast)', () => {
  it('the last 4 seconds count as finished (polling misses the end)', () => {
    expect(speakerOutcome(197, 200, false)).toBe('complete')
  })
  it('stopping the music early is not a skip', () => {
    expect(speakerOutcome(5, 200, true)).toBeNull()
    expect(speakerOutcome(5, 200, false)).toBe('skip')
  })
  it('nothing without a position', () => expect(speakerOutcome(0, 200, false)).toBeNull())
})
