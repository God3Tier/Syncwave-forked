# Demo seed

The demo songs in `songs.txt` give the UI something to play straight after a stack starts: Daisy Bell with synced lyrics, and one song for each mood Recommendation matches to the weather. The four mood songs have no lyrics.

| Song | Mood | Comes first in |
|---|---|---|
| Daisy Bell | none | never (always a general pick) |
| Gymnopédie No. 1 | calm | rain, storm, fog, snow |
| Nocturne Op. 9 No. 2 | mellow | rain, storm, cloudy |
| Maple Leaf Rag | upbeat | clear |
| The Stars and Stripes Forever | energetic | clear |

**Local stack.** The one-shot `seed` service in `docker-compose.yml` runs `seed.sh` on every start. For each song it puts the audio (and lyrics) in S3 and publishes `SongUploaded`, exactly as the Upload Service would; Catalogue, Lyrics and Waveform then process it. The song and event IDs in `songs.txt` are fixed, so starting again only re-sends the same events, which the consumers recognise and skip.

**Any other stack** (such as AWS, which has no `seed` service): `upload-songs.py` uploads the same songs through the Upload API and waits until they are processed. Songs whose title and artist are already in the Catalogue are skipped, so it is safe to run again. It needs only Python's standard library:

```sh
python infrastructure/seed/upload-songs.py --base-url http://<gateway or ALB>
```

To add a song, put its file here and add a line to `songs.txt` with new IDs (`python -c "import uuid; print(uuid.uuid4())"`). Then credit it below.

## The songs

All five are public domain. The four mood songs were transcoded from the Commons files to mono MP3 (LAME VBR quality 4, loudness-normalised to -16 LUFS), so they stay small in the repository.

**"Daisy Bell (Bicycle Built for Two)"**, written by Harry Dacre (1892) and sung by Edward M. Favor. The recording was made in 1894 on a brown wax cylinder (Edison Phonograph Co. 1058) and digitised by the UCSB Cylinder Preservation and Digitization Project (cylinder 10477).

- `daisy-bell.mp3` is Wikimedia Commons' MP3 transcode of [File:Daisy Bell sung by Edward M. Favor denoised.ogg](https://commons.wikimedia.org/wiki/File:Daisy_Bell_sung_by_Edward_M._Favor_denoised.ogg). That file has clicks and noise removed (by User:Artoria2e5).
- Commons marks the file **public domain**. The 1894 recording, and the 1892 song by a composer who died in 1922, are public domain in both the US and Singapore.

**"Gymnopédie No. 1"** (calm) by Erik Satie (1888), played by Robin Alciatore for Musopen (about 2008). `gymnopedie-no-1.mp3` is from [File:Erik Satie - gymnopedies - la 1 ere. lent et douloureux.ogg](https://commons.wikimedia.org/wiki/File:Erik_Satie_-_gymnopedies_-_la_1_ere._lent_et_douloureux.ogg). Musopen released the recording into the public domain, and Satie died in 1925.

**"Nocturne Op. 9 No. 2"** (mellow) by Frédéric Chopin (1832), played by Frank Levy for Musopen. `nocturne-op-9-no-2.mp3` is from [File:Nocturne in E flat major, Op. 9 no. 2.mp3](https://commons.wikimedia.org/wiki/File:Nocturne_in_E_flat_major,_Op._9_no._2.mp3). Musopen released the recording into the public domain, and Chopin died in 1849.

**"Maple Leaf Rag"** (upbeat) by Scott Joplin (1899), from his own 1916 piano roll. `maple-leaf-rag.mp3` is from [File:Maple leaf rag - played by Scott Joplin 1916 V2.ogg](https://commons.wikimedia.org/wiki/File:Maple_leaf_rag_-_played_by_Scott_Joplin_1916_V2.ogg), which Commons marks public domain. Joplin died in 1917.

**"The Stars and Stripes Forever"** (energetic) by John Philip Sousa (1896), played by the United States Marine Band (2017 album). `stars-and-stripes-forever.mp3` is from [File:Sousa's "The Stars and Stripes Forever" - United States Marine Band (2017).mp3](https://commons.wikimedia.org/wiki/File:Sousa%27s_%22The_Stars_and_Stripes_Forever%22_-_United_States_Marine_Band_(2017).mp3). The recording is a work of the US federal government, so it is public domain, and Sousa died in 1932.

## How the lyric timings were made

`daisy-bell.lrc` uses the 1892 lyrics: two verses, each followed by the chorus. The recording is too noisy for reliable speech recognition, so the timings are estimates. They were built in three steps:

1. **Anchors.** whisper.cpp (`small.en`, run on the vocal band) recognised the second half phonetically, for example "when the night's down, we can roll to try" for "when the road's dark we can both despise". These gave fixed points.
2. **Metre.** The song is a waltz in which each half-line of lyrics lasts about 3.5 s, so the remaining line starts follow from that.
3. **Breaths.** The line starts were snapped to the dips in the vocal-band loudness, where the singer breathes between lines.

Expect lines to be within about a second of the singing. If a line is visibly early or late when you listen, adjust its `[mm:ss.xx]` tag. Then run `docker compose down -v && docker compose up -d --wait`, because Lyrics keeps a processed song and won't reprocess it.
