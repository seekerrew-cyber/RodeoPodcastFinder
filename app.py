from pathlib import Path

import streamlit as st

import botctl
import finder
import library

LOGO = Path(__file__).parent / "logo.png"
PAGE_SIZE = 10
YT_URL = "https://www.youtube.com/watch?v={}"

st.set_page_config(page_title="Rodeo", page_icon="🤠", layout="wide")


@st.cache_data(show_spinner=False)
def cached_videos():
    return library.list_videos()


def fmt_time(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def set_play(video_id, start):
    st.session_state["play"] = {"vid": video_id, "start": int(start)}


# ---------------------------------------------------------------- หน้า 1: ค้นหา
def page_search():
    st.header("ค้นหาเรื่องจากเรื่องย่อ")
    st.caption("ใส่เรื่องย่อที่จำได้ แล้วหาว่าอยู่คลิปไหนของช่อง")

    summary = st.text_area(
        "เรื่องย่อ",
        height=160,
        placeholder="เช่น ผู้หญิงย้ายเข้าหอพักเก่า ได้ยินเสียงเคาะประตูทุกคืนตอนตีสาม...",
    )
    top = st.slider("จำนวนผลลัพธ์", 1, 10, 5)

    if st.button("ค้นหา", type="primary", disabled=not summary.strip()):
        with st.spinner("กำลังเหวี่ยงเชือก..."):
            results = finder.search(summary, top)
        if not results:
            st.warning("ยังไม่มีข้อมูลใน index หรือไม่พบผลลัพธ์")
        for r in results:
            with st.container(border=True):
                st.markdown(f"### [{r['title']}]({r['url']})")
                st.progress(min(max(r["score"], 0.0), 1.0), text=f"ความคล้าย {r['score']:.1%}")
                if r.get("kind") == "summary":
                    st.caption(f"ตรงกับเรื่องย่อที่ผู้ใช้เขียนไว้ · ตรง {r['matched_chunks']} ท่อน")
                else:
                    st.caption(
                        f"ท่อนที่ตรงที่สุดเริ่มที่ {fmt_time(r['start'])} · ตรง {r['matched_chunks']} ท่อน"
                    )
                st.write(r["snippet"])


# ---------------------------------------------------------------- หน้า 2: เพิ่มข้อมูล
def page_index():
    st.header("เพิ่มข้อมูลจากช่อง")
    if botctl.status()["running"]:
        st.warning(
            "Discord บอททำงานอยู่ Chroma ไม่เหมาะกับการเขียนจากหลายโปรเซสพร้อมกัน "
            "ควรหยุดบอทก่อน index หรือใช้คำสั่ง /reindex ของบอทแทน",
            icon="⚠️",
        )
    st.caption(
        "ส่งลิงก์ช่อง YouTube เพื่อดึง transcript มาใส่ฐานข้อมูล คลิปที่เคย index แล้วจะถูกข้าม "
        "(ระหว่างที่กำลัง index ไม่ควรเปลี่ยนไปหน้าอื่น เพราะจะทำให้การทำงานหยุด)"
    )

    channel = st.text_input("URL ช่อง", placeholder="https://www.youtube.com/@xxxx")
    c1, c2 = st.columns(2)
    limit = c1.number_input("จำนวนคลิปล่าสุด (0 = ทั้งหมด)", min_value=0, value=0)
    whisper = c2.checkbox("ใช้ Whisper ถ้าไม่มี subtitle (ช้า)")

    if st.button("เริ่ม index", type="primary", disabled=not channel.strip()):
        box = st.empty()
        lines = []

        def log(msg):
            lines.append(msg)
            box.code("\n".join(lines[-15:]))

        finder.index_channel(channel.strip(), whisper, limit or None, log)
        cached_videos.clear()
        st.success("เสร็จแล้ว ไปดูผลได้ที่เมนู 'คลังเรื่อง'")


# ---------------------------------------------------------------- หน้า 3: คลังเรื่อง
def video_label(v):
    tag = " · ✎ มีเรื่องย่อ" if v["has_summary"] else ""
    return f"{v['title']}  ({v['chunks']} ท่อน){tag}"


def page_library():
    st.header("คลังเรื่อง")

    videos = cached_videos()
    if not videos:
        st.info("ยังไม่มีข้อมูลในฐานข้อมูล ไปที่เมนู 'เพิ่มข้อมูลจากช่อง' ก่อน")
        return

    by_id = {v["video_id"]: v for v in videos}
    vid = st.selectbox(
        "เลือกเรื่อง (พิมพ์เพื่อค้นหาชื่อได้)",
        list(by_id),
        format_func=lambda x: video_label(by_id[x]),
    )
    video = by_id[vid]
    transcript, summary = library.get_chunks(vid)

    # เครื่องเล่นอยู่ใน sidebar เพื่อให้เห็นตลอดตอนเลื่อนดู transcript
    play = st.session_state.get("play", {})
    start = play.get("start", 0) if play.get("vid") == vid else 0
    with st.sidebar:
        st.divider()
        st.caption("เครื่องเล่น")
        st.video(YT_URL.format(vid), start_time=start)

    st.markdown(f"**{video['title']}** · [เปิดบน YouTube ↗]({YT_URL.format(vid)})")

    tab_tr, tab_sum = st.tabs(["Transcript", "เรื่องย่อของฉัน"])

    # ----- Transcript
    with tab_tr:
        st.warning(
            "การแก้ไขข้อความจะคำนวณ embedding ของท่อนนั้นใหม่ ทำให้ผลการค้นหาเปลี่ยนไปจากที่เคยได้ "
            "(คลิปนี้อาจขึ้นหรือหล่นอันดับต่างจากเดิม) และไม่มีปุ่มย้อนกลับ",
            icon="⚠️",
        )
        q = st.text_input("กรองคำใน transcript", placeholder="พิมพ์คำที่จำได้...", key=f"flt_{vid}")
        rows = [r for r in transcript if q.strip().lower() in r["text"].lower()] if q.strip() else transcript

        if not rows:
            st.caption("ไม่พบท่อนที่ตรงกับคำที่กรอง")
        else:
            total_pages = max(1, -(-len(rows) // PAGE_SIZE))
            pg = 1
            if total_pages > 1:
                pg = st.number_input(
                    f"หน้า (ทั้งหมด {total_pages} หน้า · {len(rows)} ท่อน)",
                    min_value=1,
                    max_value=total_pages,
                    value=1,
                    key=f"pg_{vid}_{q}",
                )
            for ch in rows[(pg - 1) * PAGE_SIZE : pg * PAGE_SIZE]:
                with st.container(border=True):
                    c1, c2 = st.columns([1, 5])
                    with c1:
                        st.button(
                            f"▶ {fmt_time(ch['start'])}",
                            key=f"play_{ch['id']}",
                            on_click=set_play,
                            args=(vid, ch["start"]),
                            help="เล่นในเครื่องเล่นด้านซ้าย",
                        )
                        st.markdown(f"[เปิดบน YouTube ↗]({YT_URL.format(vid)}&t={ch['start']}s)")
                    with c2:
                        new = st.text_area(
                            "ข้อความ",
                            value=ch["text"],
                            key=f"txt_{ch['id']}",
                            height=130,
                            label_visibility="collapsed",
                        )
                        changed = new.strip() != ch["text"].strip()
                        if st.button("บันทึกการแก้ไข", key=f"save_{ch['id']}", disabled=not changed):
                            try:
                                library.update_chunk(ch["id"], new)
                                st.toast("บันทึกแล้ว และคำนวณ embedding ใหม่เรียบร้อย", icon="✅")
                            except Exception as e:
                                st.error(f"บันทึกไม่สำเร็จ: {e}")

    # ----- เรื่องย่อของผู้ใช้
    with tab_sum:
        st.caption(
            "เรื่องย่อที่คุณเขียนจะถูกเพิ่มเป็นส่วนหนึ่งของข้อมูลที่ใช้ค้นหา (semantic search) "
            "ของคลิปนี้ เหมาะกับการเขียนสรุปด้วยภาษาของคุณเอง เช่น ตัวละคร เหตุการณ์สำคัญ ฉากจบ"
        )
        text = st.text_area(
            "เรื่องย่อ",
            value=summary["text"] if summary else "",
            height=180,
            key=f"sum_{vid}",
            placeholder="เช่น ชายคนหนึ่งซื้อบ้านเก่า แล้วพบว่าห้องใต้ดินมีประตูที่เมื่อวานยังไม่มี...",
        )
        st.caption("ถ้าเว้นว่างแล้วกดบันทึก = ลบเรื่องย่อของคลิปนี้")
        if st.button("บันทึกเรื่องย่อ", type="primary", key=f"sumsave_{vid}"):
            try:
                library.save_summary(vid, video["title"], text)
                cached_videos.clear()
                st.toast("บันทึกเรื่องย่อแล้ว" if text.strip() else "ลบเรื่องย่อแล้ว", icon="✅")
            except Exception as e:
                st.error(f"บันทึกไม่สำเร็จ: {e}")


# ---------------------------------------------------------------- หน้า 4: Discord บอท
BOT_MSGS = {
    "started": ("success", "เริ่มบอทแล้ว กำลังโหลดโมเดล อาจใช้เวลาประมาณหนึ่งนาที ดูความคืบหน้าที่ Log ด้านล่าง"),
    "already_running": ("info", "บอททำงานอยู่แล้ว"),
    "no_token": ("error", "ยังไม่ได้บันทึก Bot token"),
    "no_bot_file": ("error", "ไม่พบ bot.py ในโฟลเดอร์เดียวกับ app.py"),
    "stopped": ("success", "หยุดบอทแล้ว"),
    "not_running": ("info", "บอทไม่ได้ทำงานอยู่"),
}


def _bot_action(action):
    _, code = botctl.start() if action == "start" else botctl.stop()
    st.session_state["bot_msg"] = BOT_MSGS[code]


def _saved_permissions(env):
    try:
        return int(env.get("DISCORD_PERMISSIONS") or 51200)
    except ValueError:
        return 51200


def page_discord():
    st.header("Discord บอท")
    st.caption("ตั้งค่าบอท สร้างลิงก์เชิญ และเริ่ม/หยุดบอทได้จากหน้านี้")

    env = botctl.load_env()

    # ----- สถานะ + เริ่ม/หยุด
    msg = st.session_state.pop("bot_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    state = botctl.status()
    if state["running"]:
        st.success(f"🟢 กำลังทำงาน · PID {state['pid']}")
    else:
        st.info("⚪ หยุดอยู่")
    c1, c2, c3 = st.columns(3)
    c1.button("▶ เริ่มบอท", type="primary", disabled=state["running"], on_click=_bot_action, args=("start",))
    c2.button("■ หยุดบอท", disabled=not state["running"], on_click=_bot_action, args=("stop",))
    c3.button("↻ รีเฟรชสถานะ")
    st.caption("แก้การตั้งค่าแล้ว ต้องหยุดบอทแล้วเริ่มใหม่ ถึงจะใช้ค่าใหม่")

    # ----- การตั้งค่า
    st.subheader("การตั้งค่า")
    with st.form("bot_settings"):
        app_id = st.text_input(
            "Application ID (ID ของบอท)",
            value=env.get("DISCORD_APP_ID", ""),
            help="Developer Portal → General Information → Application ID ใช้สร้างลิงก์เชิญเท่านั้น",
        )
        token = st.text_input(
            "Bot token",
            type="password",
            placeholder="บันทึกแล้ว เว้นว่างไว้ถ้าจะใช้ค่าเดิม" if env.get("DISCORD_TOKEN") else "วาง bot token",
            help="Developer Portal → Bot → Reset Token ไม่ใช่ Application ID หรือ Client Secret",
        )
        f1, f2 = st.columns(2)
        owner = f1.text_input(
            "User ID เจ้าของบอท",
            value=env.get("OWNER_ID", ""),
            help="User ID ใน Discord ของคุณ เฉพาะคนนี้ที่ใช้ /reindex ได้",
        )
        min_score = f2.text_input(
            "คะแนนตรงขั้นต่ำ (MIN_SCORE)",
            value=env.get("MIN_SCORE", "0.35"),
            help="ถ้าต่ำกว่าค่านี้ บอทจะตอบว่าไม่พบเรื่องที่ตรง",
        )
        perms = st.multiselect(
            "สิทธิ์ของบอท (Permissions)",
            list(botctl.PERMISSIONS),
            default=botctl.names_from_int(_saved_permissions(env)),
        )
        saved = st.form_submit_button("บันทึกการตั้งค่า")

    if saved:
        errors = []
        if app_id.strip() and not botctl.valid_app_id(app_id):
            errors.append("Application ID ต้องเป็นตัวเลขล้วน (15-25 หลัก)")
        if owner.strip() and not owner.strip().isdigit():
            errors.append("User ID เจ้าของบอทต้องเป็นตัวเลขล้วน")
        try:
            float(min_score)
        except ValueError:
            errors.append("คะแนนตรงขั้นต่ำต้องเป็นตัวเลข เช่น 0.35")
        if errors:
            for e in errors:
                st.error(e)
        else:
            updates = {
                "DISCORD_APP_ID": app_id.strip() or None,
                "OWNER_ID": owner.strip() or None,
                "MIN_SCORE": min_score.strip(),
                "DISCORD_PERMISSIONS": str(botctl.permissions_int(perms)),
            }
            if token.strip():
                updates["DISCORD_TOKEN"] = token.strip()
                if token.strip().count(".") != 2:
                    st.warning("ค่าที่ใส่ไม่เหมือน Bot token (ปกติมี 3 ส่วนคั่นด้วยจุด) เช็กว่าไม่ได้ใส่ Application ID แทน")
            botctl.save_env(updates)
            env = botctl.load_env()
            st.success("บันทึกลง .env แล้ว (ถ้าบอททำงานอยู่ ต้องหยุดแล้วเริ่มใหม่)")
    st.caption(
        "การตั้งค่าถูกเก็บเป็นข้อความธรรมดาใน .env ห้าม commit ไฟล์นี้ "
        "และหน้านี้ไม่มีระบบล็อกอิน อย่าเปิดแอปให้คนอื่นเข้าถึงจากอินเทอร์เน็ต"
    )

    # ----- ลิงก์เชิญ
    st.subheader("ลิงก์เชิญบอท")
    saved_id = env.get("DISCORD_APP_ID", "")
    if botctl.valid_app_id(saved_id):
        perm_int = _saved_permissions(env)
        url = botctl.invite_url(saved_id, perm_int)
        st.code(url, language=None)
        st.markdown(f"[เปิดลิงก์เชิญ ↗]({url})")
        note = f"Permissions integer: {perm_int}"
        if perm_int == 51200:
            note += " (Send Messages + Embed Links + Attach Files)"
        st.caption(note + " · scope: bot + applications.commands · ผู้เชิญต้องมีสิทธิ์ Manage Server ในเซิร์ฟเวอร์นั้น")
    else:
        st.info("ใส่ Application ID (ตัวเลขล้วน) ด้านบนแล้วบันทึก เพื่อสร้างลิงก์เชิญ")

    # ----- Log
    st.subheader("Log")
    log = botctl.tail_log()
    if not state["running"] and "token is invalid" in log.lower():
        st.warning("Discord ปฏิเสธ token ให้ใช้ Bot token จากแท็บ Bot → Reset Token (ไม่ใช่ตัวเลข Application ID)")
    st.code(log or "ยังไม่มี log", language=None)


# ---------------------------------------------------------------- เมนูซ้าย
PAGES = {
    "🔎 ค้นหา": page_search,
    "➕ เพิ่มข้อมูลจากช่อง": page_index,
    "📚 คลังเรื่อง": page_library,
    "🤖 Discord บอท": page_discord,
}

with st.sidebar:
    if LOGO.exists():
        st.image(str(LOGO), width=160)
    choice = st.radio("เมนู", list(PAGES), label_visibility="collapsed")
    st.caption(f"ใน index ตอนนี้: {finder.get_collection().count():,} chunks")
    st.caption("🤖 บอท: " + ("ทำงานอยู่" if botctl.status()["running"] else "หยุดอยู่"))

PAGES[choice]()