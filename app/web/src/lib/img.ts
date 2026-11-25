// Artwork helpers: request the right size from Google's image CDN, and read a cover's dominant colour
// (through the same-origin /img proxy, so the canvas isn't tainted).

export function sized(url: string | null | undefined, px: number): string {
  if (!url) return ''
  if (url.includes('googleusercontent.com') || url.includes('ggpht.com')) {
    const s = Math.round(px * Math.min(2, window.devicePixelRatio || 1))
    return url.replace(/=w\d+-h\d+[^/]*$/, `=w${s}-h${s}-l90-rj`).replace(/=s\d+[^/]*$/, `=s${s}`)
  }
  if (url.includes('i.ytimg.com') && px <= 120) return url.replace(/\/(hq|sd|maxres)default\.jpg/, '/mqdefault.jpg')
  return url
}

export function large(url: string | null | undefined) { return sized(url, 544) }

const colorCache = new Map<string, [number, number, number]>()

/** Dominant, reasonably vivid colour of an image as [r, g, b] (null on failure). */
export function dominant(url: string): Promise<[number, number, number] | null> {
  if (!url) return Promise.resolve(null)
  const hit = colorCache.get(url)
  if (hit) return Promise.resolve(hit)
  return new Promise((resolve) => {
    const img = new Image()
    img.decoding = 'async'
    img.onload = () => {
      try {
        const n = 24, c = document.createElement('canvas')
        c.width = c.height = n
        const ctx = c.getContext('2d', { willReadFrequently: true })!
        ctx.drawImage(img, 0, 0, n, n)
        const d = ctx.getImageData(0, 0, n, n).data
        let r = 0, g = 0, b = 0, w = 0
        for (let i = 0; i < d.length; i += 4) {
          const R = d[i], G = d[i + 1], B = d[i + 2]
          const mx = Math.max(R, G, B), mn = Math.min(R, G, B)
          const sat = mx ? (mx - mn) / mx : 0, lum = (mx + mn) / 510
          const wt = 0.05 + sat * sat * (lum > 0.08 && lum < 0.92 ? 1 : 0.1)   // favour saturated mid-tones
          r += R * wt; g += G * wt; b += B * wt; w += wt
        }
        const out: [number, number, number] = [Math.round(r / w), Math.round(g / w), Math.round(b / w)]
        colorCache.set(url, out)
        resolve(out)
      } catch { resolve(null) }
    }
    img.onerror = () => resolve(null)
    img.src = '/img?u=' + encodeURIComponent(url)
  })
}

/** Accent colours from a base colour: a light accent for text/controls and a deep tint for backgrounds. */
export function palette([r, g, b]: [number, number, number]) {
  const max = Math.max(r, g, b) / 255, min = Math.min(r, g, b) / 255
  let h = 0
  const l = (max + min) / 2, d = max - min
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1))
  if (d) {
    const R = r / 255, G = g / 255, B = b / 255
    h = max === R ? ((G - B) / d) % 6 : max === G ? (B - R) / d + 2 : (R - G) / d + 4
    h = Math.round(h * 60 + 360) % 360
  }
  const sat = Math.round(Math.min(85, Math.max(35, s * 100)))
  return { accent: `hsl(${h} ${sat}% 68%)`, tint: `hsl(${h} ${Math.min(60, sat)}% 22%)`, tintSoft: `hsl(${h} ${Math.min(50, sat)}% 14%)` }
}
