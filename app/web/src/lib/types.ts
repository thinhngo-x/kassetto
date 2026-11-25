export interface Song {
  type: 'song'
  videoId: string
  title: string
  artist: string
  album?: string
  duration?: number | null
  thumb?: string | null
  auto?: boolean          // added by Autoplay
  why?: string            // which recommender source picked it
  because?: string        // the specific reason ("Sounds like Numb", "Because you like …")
  retried?: boolean
}

export type Kind = 'album' | 'artist' | 'playlist' | 'mix' | 'lbplaylist' | 'versions' | 'myplaylist'

export interface Item {
  type: Kind
  id: string
  title: string
  sub?: string
  thumb?: string | null
}

export type Entry = Song | Item

export interface Shelf { title: string; items: Entry[] }
export interface PersonalShelf { shelf: string; items: Entry[] }

export interface Detail {
  title: string
  sub?: string
  thumb?: string | null
  tracks: Song[]
  albums?: Item[]
  meta?: { id: string; owner: string; shared: boolean; kind: 'user' | 'weekly' | 'daily'; mine: boolean }
}

export interface Taste {
  ytm_plays: number
  listenbrainz_listens: number
  likes: number
  hidden: number
  boredom?: number
  ranker?: { updates: number; served: number; labelled: number; weights: Record<string, { now: number; start: number }> }
  session?: { plays: number }
  top_artists: [string, number][]
  embedded: number
  embed_queue: number
  taste_clusters: { weight: number; songs: string[] }[]
  sources: Record<string, number>
  signals?: Record<string, number>
}

export interface NestStatus {
  active: boolean
  videoId?: string
  index?: number
  state?: string
  position?: number
  duration?: number | null
  sleep_at?: number | null
}
