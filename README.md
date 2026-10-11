
<h1 align="center">Rodeo — Find YouTube podcast episodes by what happens in them</h1>

<p align="center">
  <img src="logo (14).png" alt="Rodeo  logo" width="420">
</p>
<p align="center">
  <b>Remember the story but forgot the title? Rodeo finds the episode with semantic search.</b><br>
  <sub>Semantic search matches the meaning of what you describe, not the exact words.</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-orange.svg" alt="MIT License">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+">
</p>

---

You remember the plot, but not the title. Rodeo  searches what is actually *said* in a YouTube channel's videos, not just their titles and descriptions. Paste a short summary of the story, and Rodeo  returns the closest matching videos, with a link that jumps to the exact moment.

It was built for storytelling channels (horror stories, true crime, narrated Reddit posts and the like), where titles are often clickbait and don't reflect the content. It works with any channel that has subtitles, or audio that can be transcribed.

Use it three ways: a **command line**, a **web UI**, or a **Discord bot**.

## Features

- **Semantic search over transcripts.** Matches by meaning, so your wording doesn't need to match the story's.
- **Multilingual.** Uses [BGE-M3](https://huggingface.co/BAAI/bge-m3) embeddings by default, which handle Thai, English and 100+ other languages.
- **Timestamped results.** Each result links to the best-matching moment in the video.
- **Video-level ranking.** Scores combine the single best passage with the average of the top three, so a video with several matching passages beats one with a lucky single match.
- **Incremental indexing.** Re-running the indexer skips videos that are already indexed.
- **Whisper fallback.** If a video has no subtitles, optionally transcribe it locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
- **Runs locally.** Embeddings are computed on your machine and stored in a local [Chroma](https://www.trychroma.com/) database.

## How it works

```
 YouTube channel
       │  yt-dlp (list videos)
       ▼
  Transcripts ── youtube-transcript-api, or faster-whisper as a fallback
       │  split into ~500-character chunks
       ▼
  Embeddings (BGE-M3) ──► Chroma vector database
                                  ▲
 Your plot summary ──► embedding ─┘  nearest chunks ──► ranked videos + timestamps
```

1. **Index.** Rodeo  lists the channel's videos, fetches each transcript, splits it into overlapping chunks, embeds them, and stores them.
2. **Search.** Your summary is embedded the same way and compared against every chunk.
3. **Rank.** Matching chunks are grouped by video and scored. The top videos are returned with a link to the best chunk's timestamp.

## Installation

Requires Python 3.10 or newer.

```bash
git clone https://github.com/your-username/Rodeo .git
cd Rodeo 
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

The first run downloads the BGE-M3 model (about 2 GB). On a CPU-only machine, embedding is slow but works. For a lighter model, see [Configuration](#configuration).

## Usage

### Command line

Index a channel (start small to try it out):

```bash
python finder.py index "https://www.youtube.com/@ChannelName" --limit 20
```

Add `--whisper` to transcribe videos that have no subtitles (slow, and needs `faster-whisper`):

```bash
python finder.py index "https://www.youtube.com/@ChannelName" --whisper
```

Search:

```bash
python finder.py search "A woman moves into an old dorm and hears knocking at 3 a.m. every night" --top 5
```

### Web UI

```bash
streamlit run app.py
```

The sidebar lets you index a channel and shows how many chunks are stored. The main panel takes your summary and shows ranked results with similarity scores and matching excerpts.

### Discord bot

Rodeo  includes a bot with slash commands.

| Command | Description |
|---|---|
| `/find summary:<text> [top:1-5]` | Find videos matching a plot summary |
| `/reindex channel_url:<url> [limit:<n>]` | Update the index (bot owner only) |

**Setup**

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications), open the **Bot** tab, and copy the bot token.
2. Invite the bot to your server with this link, replacing `YOUR_APP_ID` with your Application ID:

   ```
   https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&permissions=51200&integration_type=0&scope=bot+applications.commands
   ```

   The bot only needs the `bot` and `applications.commands` scopes. It uses slash commands, so **no privileged intents** are required.
3. Set the environment variables and run:

   ```bash
   export DISCORD_TOKEN="your-bot-token"
   export OWNER_ID="your-discord-user-id"   # optional, enables /reindex
   python bot.py
   ```

   On Windows PowerShell: `$env:DISCORD_TOKEN='your-bot-token'`. If you prefer a `.env` file, load it with [python-dotenv](https://pypi.org/project/python-dotenv/).

> **Keep your token secret.** Never commit it. Discord will automatically reset tokens that are published in public repositories.

The bot must stay running to answer commands, so host it somewhere that keeps a persistent process alive.

## Configuration

All settings are environment variables.

| Variable | Default | Description |
|---|---|---|
| `STORY_DB` | `./db` | Directory for the Chroma database |
| `EMBED_MODEL` | `BAAI/bge-m3` | Any [sentence-transformers](https://www.sbert.net/) model, such as `intfloat/multilingual-e5-base` for a lighter option |
| `DISCORD_TOKEN` | none | Bot token (bot only, required) |
| `OWNER_ID` | `0` | Discord user ID allowed to run `/reindex` |
| `MIN_SCORE` | `0.35` | Below this score the bot says nothing matched. Tune it for your channel |

> If you change `EMBED_MODEL`, delete the `db` directory and re-index. Vectors from different models can't be compared.

## Project structure

```
Rodeo /
├── finder.py          # indexing + search core, and the CLI
├── app.py             # Streamlit web UI
├── bot.py             # Discord bot
├── requirements.txt
├── logo.png
├── LICENSE
└── README.md
```

## Tips for better results

- **Describe events, not themes.** "A man finds a door in his basement that wasn't there yesterday" works better than "a scary basement story".
- **Include specifics you remember**: places, jobs, objects, unusual details.
- **Prefer subtitles over guesses.** Auto-generated subtitles can misspell names. Whisper is often more accurate for names and places, but slower.
- **Tune `MIN_SCORE`.** Run a few searches you know the answer to, note the scores of correct and incorrect matches, and set the threshold between them.

## Limitations

- Quality depends on transcript quality. Videos with no subtitles and no Whisper pass can't be searched.
- Search matches what is spoken. Stories told mainly through on-screen text or music won't match well.
- Local embedding with BGE-M3 needs a few GB of RAM.
- Chroma is not designed for multiple processes writing at the same time. Don't run an indexer while the bot is running; use `/reindex` instead.

## Roadmap

Ideas, not promises:

- Optional hosted embedding API as an alternative to running the model locally
- LLM re-ranking of the top results, with a short explanation of why each matches
- Hybrid search (keyword + semantic)
- Support for playlists and multiple channels in one index

Contributions and suggestions are welcome. Open an issue to discuss before large changes.

## Responsible use

Rodeo  stores text transcribed from videos made by other people. That content belongs to its creators.

- Use Rodeo  for personal search and discovery. Don't republish or redistribute indexed transcripts.
- Always link back to the original video, as Rodeo 's results do.
- Follow [YouTube's Terms of Service](https://www.youtube.com/t/terms) and the rules of any channel or service you use.
- The `db` directory is excluded from version control. Keep it that way.

## License

Released under the [MIT License](LICENSE).