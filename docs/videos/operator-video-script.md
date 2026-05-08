# ConnectClips — Volunteer operator video script

**Target length: 8-10 min finished video.** Real-world workflow takes ~20-30 min wall-clock per sermon (mostly Whisper transcription); you'll fast-forward through wait periods.

**Audience:** Church media volunteers using ConnectClips for the first time. Assumes nothing — no command line, no AI knowledge. They've already got the URL and a working tailnet connection.

**Recording setup:**
- Use a real (or representative) sermon you have rights to. The Bosgame already has the Exodus 18 sermon as a good demo.
- Pre-load the sermon if you don't want to wait through the download + transcribe in real time. You can record the "wait" stages separately.
- Keep your face out of the recording unless you specifically want a talking-head intro — over-the-shoulder screen capture with voiceover is fine.

---

## Scene 1 — Cold open / hook (0:00 - 0:30)

**ACTION:** Title card "ConnectClips — turning a sermon into clips" over the home page screenshot, or a quick montage of three exported vertical clips.

**SAY:**
> "Welcome. This video shows you how to turn this Sunday's sermon into 5-7 short vertical clips ready to post on YouTube Shorts, TikTok, Instagram Reels, and Facebook Reels. From paste-the-link to ready-to-upload, your hands-on time is about 20 minutes. The computer does most of the work; you'll come back to a list of suggestions, pick the ones you like, trim the edges, and download them. Let's go."

---

## Scene 2 — Open the app (0:30 - 1:00)

**ACTION:** Open the ConnectClips URL in a browser (the `.ts.net` Tailscale URL). Show the home page.

**SAY:**
> "Mike will send you the link to ConnectClips. Save it as a bookmark — you'll come here every week. Make sure Tailscale is connected on your laptop or phone first, otherwise the page won't load. The very top is a banner; underneath you'll see your name in the corner, then a big 'Add a sermon' panel. Below that, any sermons that are already in the system."

---

## Scene 3 — Add a sermon from YouTube (1:00 - 2:00)

**ACTION:** Paste a YouTube URL into the From YouTube field. Click Download.

**SAY:**
> "Easiest way to add a new sermon is to paste the YouTube link of last Sunday's livestream. The system will download the full video, no need to upload anything from your laptop. Click Download.
>
> A new row appears at the top of the sermon list with a status badge that updates as it works. Right now it's downloading. Then it'll transcribe — that's the AI listening to the audio and writing out every word. Then it'll pick the best clips. Then it'll scan for faces. All four stages happen automatically; you don't have to click anything else right now."

---

## Scene 4 — The wait period (2:00 - 3:00)

**ACTION:** Show the progress badges updating across the four stages. Cut to time-lapse of the badges turning green.

**SAY:**
> "Here's where you walk away. For a typical 50-minute sermon on this hardware, give it about 15-20 minutes. You can close the browser; it'll keep running on the server. You can also click into the sermon at any time to watch progress in detail — there's a progress bar for each stage."

**[FAST-FORWARD CUE]** Speed up to show all four badges flipping to green.

**SAY:**
> "When everything's green — Transcribed, Clips selected, and you'll see a number like 7 next to clips — the sermon is ready to work on."

---

## Scene 5 — Open the sermon, see the clip cards (3:00 - 4:00)

**ACTION:** Click the sermon row. Sermon detail page loads. Scroll down to show the clip cards.

**SAY:**
> "Click the sermon row. The detail page shows the pipeline at the top, then a list of clip suggestions below.
>
> Each card has the clip's title, what range of the sermon it covers, and a few sentences explaining why the AI picked it. There's a hook score — basically how strong the opening is. 80 and above is excellent; 70 to 80 is solid; below that, consider whether the clip really stands on its own."

**ACTION:** Hover over a high-scoring clip's hook badge to show the rationale tooltip if applicable.

**SAY:**
> "Don't trust the AI's picks blindly — it's good but not perfect. Skim the titles and rationales. If a clip's title doesn't make sense out of context, or the rationale feels weak, skip that one. You usually only post 3 or 4 clips per sermon anyway, not all of them."

---

## Scene 6 — Click into a clip, the trim view (4:00 - 5:30)

**ACTION:** Click "Preview / trim / export" on a clip.

**SAY:**
> "Click 'Preview / trim / export' on a clip you want to work on. This is where most of your time goes. Three areas:
>
> Left side: the source sermon video, scrubbable. Below it: trim controls. Right side: the live preview of what your clip will look like, with captions overlaid in real time."

**ACTION:** Hit the play button on the source video. Show the in/out time markers.

**SAY:**
> "The clip is set to start at the beginning of what the AI thought was the moment, and end at the end. You can adjust either edge. The most common adjustment is shaving the beginning — sometimes the AI starts the clip mid-sentence and you want a cleaner opening. Use the In and Out buttons under the video to set them to wherever the playhead is, or drag the time directly in the boxes."

---

## Scene 7 — Caption style + hook title + face (5:30 - 6:30)

**ACTION:** Click the caption-style dropdown. Switch between two or three styles, showing the live preview update.

**SAY:**
> "Captions are baked into the video — they show automatically based on the transcript. Pick a style from the dropdown. There are several options. Let me cycle through a couple — you can see the live preview updates as you change."

**ACTION:** Toggle the Hook Title checkbox off and back on.

**SAY:**
> "The hook title is the AI-suggested title that flashes on screen for the first couple seconds of the clip. You can turn it off if you don't like it for this clip."

**ACTION:** If a face picker is visible, hover over it briefly. Don't change selection.

**SAY:**
> "If multiple people are visible in the sermon — say there's a guest speaker — a face strip might appear. Click whichever face you want the camera to track. Otherwise leave it on Auto and it'll follow the most prominent face on screen at any given moment."

---

## Scene 8 — Export the clip (6:30 - 7:30)

**ACTION:** Click **Export vertical clip**. Show progress (extract → encode → done).

**SAY:**
> "When the trim and the style look right, click Export vertical clip. The system extracts your slice, reframes it to vertical 9 by 16, burns the captions in, and gives you the final MP4. Takes a minute or two."

**[FAST-FORWARD CUE]** Speed through the encoding progress bar.

**ACTION:** Show the exported preview appearing on the right.

**SAY:**
> "When it's done, the exported clip plays on the right side. Watch it. Captions sync? The right person centered? If anything's off, adjust your trim or style and re-export."

---

## Scene 9 — The Publish panel (7:30 - 9:00)

**ACTION:** Scroll down to or zoom in on the Publish panel below the export preview.

**SAY:**
> "Below the preview is the Publish panel. Three buttons across the top:
>
> Download MP4 — saves the clip to your laptop's Downloads folder.
>
> Copy title — copies the clip's title to your clipboard so you can paste it as the post caption on each platform.
>
> Copy full-sermon link — gives you a YouTube link that jumps directly into the original sermon at this clip's timestamp. Useful as the 'Related video' field on a YouTube Short, or in the description of a Reel.
>
> Below those, four colored buttons — YouTube, TikTok, Facebook, Instagram. Each opens that platform's upload page in a new tab. If Mike has set up the Settings page, these go straight to the church's account; if not, they open the generic upload page and you make sure you're signed into the right account before posting."

---

## Scene 10 — The schedule, don't post live, message (9:00 - 9:45)

**ACTION:** Click one of the platform buttons (e.g. YouTube) to show the upload page open. Don't actually upload.

**SAY:**
> "Important rule: don't hit Post immediately. Schedule. Each platform has a Schedule option in the upload flow — pick a time when your audience is actually watching. For our church, that's typically Tuesday morning around 9 a.m. and Friday afternoon around 4 p.m. for the highest engagement. Stagger your clips across the week — if you have 4 clips, post one every couple days, not all on Sunday afternoon when nobody's looking. The platforms reward consistency more than volume."

---

## Scene 11 — Wrap (9:45 - 10:00)

**ACTION:** Cut back to the home page or a closing card.

**SAY:**
> "That's the whole flow. Paste a link, walk away, come back, trim what you like, export, schedule, repeat. If you get stuck on something, ask Mike — there's also an operator manual in the repo with screenshots of every step. Thanks for serving the church this way."

---

## Production notes

- Two FAST-FORWARD cues (the Whisper wait, the export encode) compress ~20 min of real time into ~30 sec.
- For Scene 5 (clip cards), use a sermon with at least 5-7 generated clips so the screen is full but not chaotic.
- For Scene 7 (face picker), pick a sermon clip that actually has a face strip — not all clips do. Skip that beat if your demo clip is single-pastor only.
- If you record live narration over the screen capture, plan one take per scene and edit them together. If you do voiceover after, leave 2-3 sec of dead air at scene transitions for breathing room.
- End-of-video CTA: link to the operator manual (`docs/operator-manual.md`) in the description.
