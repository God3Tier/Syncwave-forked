# Demo seed

The one-shot `seed` service in `docker-compose.yml` loads one song into a fresh local stack. It puts the audio and lyrics in S3 and publishes `SongUploaded`, exactly as the Upload Service would. Catalogue, Lyrics and Waveform then process it, so the UI has something to play straight after `docker compose up`.

The service runs `seed.sh` on every start. Its song and event IDs are fixed, so starting again only re-sends the same event, which the consumers recognise and skip.

## The song

**"Daisy Bell (Bicycle Built for Two)"**, written by Harry Dacre (1892) and sung by Edward M. Favor. The recording was made in 1894 on a brown wax cylinder (Edison Phonograph Co. 1058) and digitised by the UCSB Cylinder Preservation and Digitization Project (cylinder 10477).

- `daisy-bell.mp3` is Wikimedia Commons' MP3 transcode of [File:Daisy Bell sung by Edward M. Favor denoised.ogg](https://commons.wikimedia.org/wiki/File:Daisy_Bell_sung_by_Edward_M._Favor_denoised.ogg). That file has clicks and noise removed (by User:Artoria2e5).
- Commons marks the file **public domain**. The 1894 recording, and the 1892 song by a composer who died in 1922, are public domain in both the US and Singapore.

## How the lyric timings were made

`daisy-bell.lrc` uses the 1892 lyrics: two verses, each followed by the chorus. The recording is too noisy for reliable speech recognition, so the timings are estimates. They were built in three steps:

1. **Anchors.** whisper.cpp (`small.en`, run on the vocal band) recognised the second half phonetically, for example "when the night's down, we can roll to try" for "when the road's dark we can both despise". These gave fixed points.
2. **Metre.** The song is a waltz in which each half-line of lyrics lasts about 3.5 s, so the remaining line starts follow from that.
3. **Breaths.** The line starts were snapped to the dips in the vocal-band loudness, where the singer breathes between lines.

Expect lines to be within about a second of the singing. If a line is visibly early or late when you listen, adjust its `[mm:ss.xx]` tag. Then run `docker compose down -v && docker compose up -d --wait`, because Lyrics keeps a processed song and won't reprocess it.
