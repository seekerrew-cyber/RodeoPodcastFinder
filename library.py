"""
ฟังก์ชันสำหรับดู/แก้ข้อมูลใน index (ใช้โดย app.py)
ใช้ finder.get_collection() และ finder.embed() ตัวเดิม จึงไม่ต้องแก้ finder.py

โครงสร้างข้อมูลใน Chroma:
  - chunk ของ transcript : id = "<video_id>:<n>"      metadata: video_id, title, start
  - เรื่องย่อของผู้ใช้     : id = "<video_id>:summary"  metadata: video_id, title, start=0, kind="summary"
"""
import finder


def list_videos():
    """คืนรายการวิดีโอใน index พร้อมจำนวน chunk และสถานะเรื่องย่อ เรียงตามชื่อ"""
    col = finder.get_collection()
    metas = col.get(include=["metadatas"])["metadatas"]
    videos = {}
    for m in metas:
        v = videos.setdefault(
            m["video_id"],
            {"video_id": m["video_id"], "title": m.get("title", ""), "chunks": 0, "has_summary": False},
        )
        if m.get("kind") == "summary":
            v["has_summary"] = True
        else:
            v["chunks"] += 1
    return sorted(videos.values(), key=lambda v: v["title"])


def get_chunks(video_id):
    """คืน (transcript_chunks เรียงตามเวลา, summary หรือ None)"""
    col = finder.get_collection()
    res = col.get(where={"video_id": video_id}, include=["documents", "metadatas"])
    transcript, summary = [], None
    for cid, doc, meta in zip(res["ids"], res["documents"], res["metadatas"]):
        row = {"id": cid, "text": doc, "start": int(meta.get("start", 0))}
        if meta.get("kind") == "summary":
            summary = row
        else:
            transcript.append(row)
    transcript.sort(key=lambda r: r["start"])
    return transcript, summary


def update_chunk(chunk_id, text):
    """แก้ข้อความของ chunk และคำนวณ embedding ใหม่"""
    text = text.replace("\x00", " ").strip()
    if not text:
        raise ValueError("ข้อความว่างไม่ได้")
    col = finder.get_collection()
    col.update(ids=[chunk_id], documents=[text], embeddings=finder.embed([text]))


def save_summary(video_id, title, text):
    """บันทึกเรื่องย่อของผู้ใช้เป็น chunk หนึ่งของวิดีโอ (ถ้าเว้นว่าง = ลบเรื่องย่อ)"""
    col = finder.get_collection()
    sid = f"{video_id}:summary"
    text = text.replace("\x00", " ").strip()
    if not text:
        col.delete(ids=[sid])
        return
    col.upsert(
        ids=[sid],
        documents=[text],
        embeddings=finder.embed([text]),
        metadatas=[{"video_id": video_id, "title": title, "start": 0, "kind": "summary"}],
    )
