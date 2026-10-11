"""
Story Finder: ใส่เรื่องย่อ -> หาคลิปจากช่อง YouTube ที่เนื้อเรื่องตรงกัน

CLI:
    python finder.py index https://www.youtube.com/@ชื่อช่อง [--whisper] [--limit 50]
    python finder.py search "เรื่องย่อที่อยากหา..." [--top 5]
"""
import argparse
import os
import tempfile
from collections import defaultdict

import chromadb
import yt_dlp

DB_PATH = os.environ.get("STORY_DB", "./db")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")
COLLECTION = "stories"

_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def embed(texts):
    return get_model().encode(
        texts, normalize_embeddings=True, batch_size=16, show_progress_bar=False
    ).tolist()


def get_collection():
    client = chromadb.PersistentClient(path=DB_PATH)
    return client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})


# ---------- 1) รายการวิดีโอ ----------
def list_videos(channel_url):
    url = channel_url.rstrip("/")
    if ("@" in url or "/channel/" in url or "/c/" in url) and not url.endswith("/videos"):
        url += "/videos"
    opts = {"extract_flat": True, "quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return [
        {"id": e["id"], "title": e.get("title") or ""}
        for e in (info.get("entries") or [])
        if e and e.get("id")
    ]


# ---------- 2) ดึงเนื้อเรื่อง (transcript) ----------
def fetch_subtitles(video_id):
    """คืน list ของ (start_seconds, text) หรือ None ถ้าไม่มี subtitle"""
    from youtube_transcript_api import YouTubeTranscriptApi

    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=["th", "en"])
        return [(s.start, s.text.replace("\n", " ")) for s in fetched]
    except Exception:
        return None


def transcribe_whisper(video_id, model_size="medium"):
    from faster_whisper import WhisperModel

    with tempfile.TemporaryDirectory() as tmp:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmp, "a.%(ext)s"),
            "quiet": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        audio = os.path.join(tmp, os.listdir(tmp)[0])
        model = WhisperModel(model_size, compute_type="auto")
        segments, _ = model.transcribe(audio, language="th", vad_filter=True)
        return [(s.start, s.text.strip()) for s in segments]


# ---------- 3) แบ่ง chunk ----------
def make_chunks(segs, max_chars=500, overlap=1):
    chunks, buf = [], []
    for seg in segs:
        buf.append(seg)
        if sum(len(t) for _, t in buf) >= max_chars:
            chunks.append((buf[0][0], " ".join(t for _, t in buf)))
            buf = buf[-overlap:] if overlap else []
    if buf and (not chunks or len(buf) > overlap):
        chunks.append((buf[0][0], " ".join(t for _, t in buf)))
    return chunks


# ---------- 4) index ----------
def index_channel(channel_url, use_whisper=False, limit=None, log=print):
    col = get_collection()
    done = {m["video_id"] for m in col.get(include=["metadatas"])["metadatas"]}
    videos = list_videos(channel_url)
    if limit:
        videos = videos[:limit]
    log(f"พบ {len(videos)} คลิป (index แล้ว {len(done)} คลิป)")

    added = 0
    for i, v in enumerate(videos, 1):
        if v["id"] in done:
            continue
        segs = fetch_subtitles(v["id"])
        if not segs and use_whisper:
            log(f"[{i}] ไม่มี subtitle -> ใช้ Whisper: {v['title']}")
            try:
                segs = transcribe_whisper(v["id"])
            except Exception as e:
                log(f"    Whisper ล้มเหลว: {e}")
        if not segs:
            log(f"[{i}] ข้าม (ไม่มี transcript): {v['title']}")
            continue

        chunks = [(s, t.replace("\x00", " ").strip()) for s, t in make_chunks(segs)]
        chunks = [c for c in chunks if c[1]]
        if not chunks:
            continue
        try:
            for b in range(0, len(chunks), 200):
                part = chunks[b:b + 200]
                col.add(
                    ids=[f"{v['id']}:{b + j}" for j in range(len(part))],
                    documents=[c[1] for c in part],
                    embeddings=embed([c[1] for c in part]),
                    metadatas=[
                        {"video_id": v["id"], "title": v["title"], "start": int(c[0])}
                        for c in part
                    ],
                )
        except Exception as e:
            log(f"[{i}] ล้มเหลว ({len(chunks)} chunks): {v['title']} -> {e}")
            try:  # ลบ chunk ที่เขียนค้างไว้ จะได้ไม่ถูกนับว่า index แล้ว
                col.delete(where={"video_id": v["id"]})
            except Exception:
                pass
            continue
        added += 1
        log(f"[{i}] index แล้ว ({len(chunks)} chunks): {v['title']}")
    log(f"เสร็จ เพิ่มใหม่ {added} คลิป")
    return added


# ---------- 5) search ----------
def search(summary, top_videos=5, top_chunks=60):
    col = get_collection()
    if col.count() == 0:
        return []
    res = col.query(
        query_embeddings=embed([summary]),
        n_results=min(top_chunks, col.count()),
        include=["metadatas", "documents", "distances"],
    )
    by_video = defaultdict(list)
    for meta, doc, dist in zip(res["metadatas"][0], res["documents"][0], res["distances"][0]):
        by_video[meta["video_id"]].append((1 - dist, meta, doc))

    results = []
    for vid, hits in by_video.items():
        hits.sort(key=lambda h: h[0], reverse=True)
        best = hits[0]
        top3 = [h[0] for h in hits[:3]]
        # คะแนนวิดีโอ = chunk ที่ตรงสุด + โบนัสถ้าหลาย chunk ในคลิปเดียวกันตรงด้วย
        score = 0.7 * best[0] + 0.3 * (sum(top3) / len(top3))
        results.append({
            "video_id": vid,
            "title": best[1]["title"],
            "score": round(score, 4),
            "start": best[1]["start"],
            "url": f"https://www.youtube.com/watch?v={vid}&t={best[1]['start']}s",
            "snippet": best[2],
            "matched_chunks": len(hits),
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_videos]


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("index")
    a.add_argument("channel")
    a.add_argument("--whisper", action="store_true", help="ถอดเสียงเองถ้าไม่มี subtitle")
    a.add_argument("--limit", type=int)
    b = sub.add_parser("search")
    b.add_argument("summary")
    b.add_argument("--top", type=int, default=5)
    args = p.parse_args()

    if args.cmd == "index":
        index_channel(args.channel, args.whisper, args.limit)
    else:
        for r in search(args.summary, args.top):
            print(f"\n[{r['score']:.3f}] {r['title']}\n  {r['url']}\n  ...{r['snippet'][:150]}...")


if __name__ == "__main__":
    main()