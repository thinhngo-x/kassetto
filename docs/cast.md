# Playing on a speaker (Chromecast / Google Home / Nest)

Kassetto can hand the queue to a Cast speaker. The speaker fetches the audio from Kassetto itself (no YouTube app,
no ads), and a small player process on the server feeds it song by song, so the music keeps going when you close
the page.

## Set up

1. **Let Kassetto see the speakers.** They announce themselves with mDNS, which doesn't cross Docker's default
   network. Either run the app container with the host's network:

   ```yaml
   services:
     kassetto:
       network_mode: host          # then drop the `ports:` section; the app listens on 8090 and 8091
   ```

   or skip discovery and give the speaker's address: `KASSETTO_SPEAKER=192.168.1.50` (optional display name:
   `KASSETTO_SPEAKER_NAME`).
2. **Pick it:** Settings → Speaker → *Find speakers* (owner only). Everyone allowed to use it then gets a cast
   button in the player.
3. **Let the speaker reach the audio port.** The speaker downloads from port **8091** of your server, so that port
   must be reachable from the speaker's network. With `network_mode: host` Kassetto works out the address itself.
   Behind Docker's NAT (or a reverse proxy) set it: `KASSETTO_STREAM_BASE=http://192.168.1.10:8091`.

Port 8091 serves the speaker only: its URLs are signed (see [sign-in.md](sign-in.md#the-audio-port-8091)). Don't
expose it to the internet.

## Who can use it

With circles, the circle marked *speaker* owns it (Settings → People): its members can cast, and wake-up music
follows its taste. Without a speaker circle, everyone can.

## Also there

- **Speaker tuning** (Settings): even loudness, an EQ for small speakers, mono mix, gentle compression. Needs the
  embed service (it renders the tuned files with ffmpeg).
- **Sleep timer:** fades out and stops on the speaker, even with the page closed.
