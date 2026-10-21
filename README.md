<div align="center">

# ✂️ bolcut

### **Bolo. Cut ho jayega.**

**Edit your video by editing the transcript.** Delete a word in the text, and that span of video is gone. Works in **Hinglish and 99 other languages**. 100% local, 100% free, MIT.

*The open-source Descript.*

[![CI](https://github.com/chirag120670598-dotcom/bolcut/actions/workflows/ci.yml/badge.svg)](https://github.com/chirag120670598-dotcom/bolcut/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue?style=flat-square)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-69%20passed-brightgreen?style=flat-square)](#-tested-where-it-matters)
[![License](https://img.shields.io/badge/license-MIT-orange?style=flat-square)](LICENSE)
[![Core deps](https://img.shields.io/badge/core%20dependencies-0-success?style=flat-square)](#-zero-core-dependencies)

**No account. No upload. No ₹2,000/month. Your footage never leaves your machine.**

</div>

---

## 🤔 The problem

[Descript](https://www.descript.com) proved that **editing video like a Word doc** is the right way to edit video. It is also **$12–24/month**, cloud-only, and its transcription is built around English.

So Indian creators either pay in USD, or they scrub a timeline by hand for three hours to remove four "matlab"s.

Meanwhile on GitHub:

| Search | Repos | Top repo |
|---|---|---|
| `open source elevenlabs alternative` | 37 | 80,030 ⭐ |
| `open source meeting transcription` | 161 | 32,011 ⭐ |
| **`open source alternative descript`** | **8** | **269 ⭐** |
| **`open source podcast editor ai`** | **3** | **265 ⭐** |
| **`transcribe hinglish`** | **67** | **8 ⭐** |

Everyone has built the open-source ElevenLabs. **Almost nobody has built the open-source Descript**, and nobody at all has built one that handles Hinglish.

---

## ✨ How it works

```bash
# 1. Transcribe locally (Whisper, no API key, no upload)
bolcut transcribe podcast.mp4 --language hi

# 2. See what it heard, with word indices
bolcut show podcast.transcript.json

# 3. Find the fillers — including YOUR verbal tics
bolcut fillers podcast.transcript.json

# 4. Preview the cut (no ffmpeg needed, works anywhere)
bolcut plan podcast.transcript.json --media podcast.mp4 \
  --output clean.mp4 --fillers --cut "to be honest"

# 5. Export
bolcut cut podcast.transcript.json --media podcast.mp4 --output clean.mp4
```

**What step 4 actually prints:**

```
Cutting 5 words (2.7s)
  4 segments kept, 3.5s of output

  CUT     0.900 ->    1.800
  CUT     2.350 ->    3.600
  CUT     4.600 ->    5.150
```

You get the exact ffmpeg command too, so you can see what will happen before it happens.

---

## 🇮🇳 Why this one is different

**1. Hinglish is a first-class input, not an afterthought.**
Built-in fillers include `arre`, `matlab`, `yani` alongside `um` and `uh`. Whisper's multilingual models handle code-mixed Hindi-English; most editing tools assume you are speaking one language.

**2. It learns YOUR tics.**
```
Your most-repeated words (candidates for --filler-words):
    34x  basically
    28x  dekho
    19x  you know
```
No list will ever contain the word *you* overuse. `bolcut fillers` finds it from your own recording.

**3. It cuts the dead air around the filler.**
Deleting "um" also removes the half-second of silence before it. That single behaviour is most of why Descript feels magical, and it is the difference between a choppy cut and a natural one.

**4. Subtitles survive the edit.**
Cut 4 seconds out of the middle and every later subtitle has to shift 4 seconds earlier. `bolcut cut` re-times them and writes a fresh `.srt`. Most DIY scripts forget this and hand you a video with drifting captions.

**5. It never touches the cloud.**
Whisper runs locally. ffmpeg runs locally. No account, no upload, no subscription, no "your 3 free exports are used up."

---

## 🧪 Tested where it matters

The timeline maths is the part that produces visible jump cuts when it is wrong, so that is what has tests:

```
$ python -m pytest -q
..................................................
69 passed in 0.11s
```

CI runs on **3 OS × 3 Python versions** (9 jobs) plus a check that the core engine stays dependency-free.

Covered cases that actually bite:

- Deleting the first / last / a middle / consecutive words
- Deleting **everything** → returns `[]`, not the unedited timeline (that bug would silently ship your original file)
- Natural pauses between kept words survive; dead air around cut words does not
- Float noise (`0.1 + 0.2 != 0.3`) cannot create a 0.0001s clip ffmpeg chokes on
- Kept + removed always sums back to the original duration — no media is lost
- Re-timed subtitles never go backwards
- Paths with apostrophes (`Chirag's demo.mp4`) are escaped for the concat demuxer
- `-c copy` is **refused** for video, because stream copy can only cut on keyframes and would silently mis-cut

---

## 🏗️ Architecture — and why it is split this way

```
bolcut/
├── core/          PURE PYTHON. Zero dependencies. Fully tested.
│   ├── transcript.py    word-level timeline, strict validation
│   ├── edits.py         the engine: deleted words -> spans to keep
│   ├── ffmpeg_plan.py   spans -> concat file + ffmpeg argv
│   ├── srt.py           rebuild subtitles for the edited file
│   └── fillers.py       filler detection + tic discovery
└── adapters/      THIN. The only code that touches the outside world.
    ├── whisper_adapter.py   faster-whisper (optional extra)
    └── ffmpeg_adapter.py    subprocess wrapper, no logic
```

`core` never imports `adapters`. That is not aesthetic — it means the part with all the edge cases runs in a plain `pytest` with no model download, no ffmpeg on PATH, and no media file.

## 📦 Zero core dependencies

`pip install bolcut` gets you the whole editing engine with **nothing else installed**. Whisper is an opt-in extra:

```bash
pip install bolcut                # engine + CLI planning
pip install bolcut[transcribe]    # + faster-whisper
# ffmpeg: brew install ffmpeg / sudo apt install ffmpeg / winget install Gyan.FFmpeg
```

## ⚠️ Honest limitations (v0.1)

- **No GUI yet.** It is a CLI. The editor UI is the next milestone.
- **No word-level "ripple" preview.** You see the cut list, not a waveform.
- **`bolcut cut` needs ffmpeg**, which bolcut will not install for you.
- I could not run ffmpeg inside the sandbox where this was written, so the
  *plan generation* is unit-tested and the *subprocess execution* is not. If
  `bolcut cut` misbehaves on your machine, open an issue with the printed
  command — `bolcut plan` shows it to you before anything runs.

---

## 🗺️ Roadmap

- [ ] **Web editor** — transcript on the left, waveform on the right, click to cut
- [ ] **Browser build** — whisper.cpp WASM, cut entirely in the tab
- [ ] **Filler auto-detect on by default** with an undo stack
- [ ] **Silence trimming** as a one-flag pass (`--silence 0.8`)
- [ ] **Multi-track / B-roll** markers
- [ ] **Export presets** for Reels, Shorts, podcast RSS

Want one of these? Open an issue — issues set the order.

## 🤝 Contribute

The highest-value contribution is a **filler list for your language**. Right now
there is English and a handful of Hinglish words. There are 21 other scheduled
Indian languages and bolcut knows none of them.

```bash
git clone https://github.com/chirag120670598-dotcom/bolcut.git
cd bolcut
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
```

Rules: core stays dependency-free, tests stay green, no fabricated behaviour.

## 📄 License

MIT © [Chirag Solanki](https://github.com/chirag120670598-dotcom)

---

<div align="center">

**Descript costs ₹2,000/month. This costs nothing and never sees your footage.**

⭐ Star it · 🍴 Fork it · 🐛 Break it and tell me

**Built in Rajkot, Gujarat 🇮🇳**

</div>
