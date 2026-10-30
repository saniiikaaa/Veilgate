"""Adds an AI voice-over to the demo video, locally (Kokoro TTS, Apache-2.0; no online service, no API key).

    pip install torch kokoro soundfile numpy        (CPU torch is enough)
    python -m spacy download en_core_web_sm         (Kokoro's text front-end needs it)
    python demo/video/voiceover.py                  # reads demo/video/out/veilgate-demo*.mp4, writes ...-voiced*.mp4
    VOICE=am_michael python demo/video/voiceover.py # another voice

Each line below starts at a fixed second of the video and must finish before the next one. If a line runs long it is sped up
slightly (never more than 1.3x); the report at the end says which ones were adjusted. Change VOICE for another voice.
"""

import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import soundfile as sf

try:  # the packaged espeak-ng has a build-machine path baked in; point it at the data that ships with the wheel
    import espeakng_loader

    os.environ.setdefault("ESPEAK_DATA_PATH", espeakng_loader.get_data_path())
except ImportError:
    pass

import misaki.espeak as _espeak  # noqa: E402


class _NoEspeak:
    """espeak-ng's own start-up aborts the whole process on some machines. Unusual words are given as explicit IPA in SAY
    instead, so the fallback is not needed."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError("espeak fallback disabled")


_espeak.EspeakFallback = _NoEspeak
from kokoro import KPipeline  # noqa: E402

OUT = Path(__file__).parent / "out"
VOICE = os.environ.get("VOICE", "af_heart")  # af_heart, af_bella, am_michael, bf_emma, bm_george ...
SPEED = float(os.environ.get("SPEED", "1.0"))
WORK = OUT / "voice"

# (start second in the video, narration). Times follow the captioned build of veilgate-demo.mp4.
LINES = [
    (0.4, "Veilgate. Governance for AI agents. Private by default, every hop traced."),
    (7.8, "AI agents now read patient records, call tools, and send email. Nobody can see what they did, or stop them leaking data."),
    (16.3, "Live detection: names and dates become vault tokens."),
    (20.5, "Edit the text and detection updates instantly. The model only ever sees the tokens."),
    (26.3, "And India's D P D P: Aadhaar, P A N, U P I."),
    (31.3, "A poisoned tool result is blocked before the agent ever reads it."),
    (36.6, "Now let's sign in and see what real agents did."),
    (44.3, "Three real agents, on NVIDIA Nemotron and Nebius Token Factory."),
    (49.3, "The model only ever sees tokens, never the patient's data."),
    (54.3, "The poisoned search result is blocked before the agent reads it."),
    (59.3, "The outside email and an unknown tool are both denied."),
    (63.3, "The task still completes, and the final answer holds no real identifiers."),
    (74.3, "Every run becomes one trace: user, agent, agent, model, tool, with a decision on every hop."),
    (81.3, "Click any hop to see what was protected, and exactly why it was blocked. Here the poisoned search costs the agent thirty points."),
    (94.3, "The sequence view tells the same story step by step. Red marks every denied or blocked step."),
    (110.2, "Authority is earned. Violations cost points. The dashed lines are gates: risky tools need a higher score, and below twenty an agent is blocked. Sub-agents are capped by their parent."),
    (127.5, "Every decision is a hash-chained receipt. Verification shows the chain intact; change history and it breaks."),
    (136.8, "Needs attention: latest violations."),
    (139.8, "Trust: a rating for every user."),
    (143.3, "Users: who runs your agents."),
    (146.6, "Test detection: try any text, even with hidden values."),
    (151.3, "Policies: every rule lives in one config file."),
    (155.2, "Veilgate runs on Nebius Token Factory with NVIDIA Nemotron. Open source under M I T, it works with any agent framework in five calls. Thanks for watching."),
]

# Words a speech model gets wrong, spelled out for it (captions are untouched).
SAY = {
    "Nebius": "[Nebius](/nˈɛbiəs/)",
    "Nemotron": "[Nemotron](/nˈɛmətɹɑn/)",
    "Aadhaar": "[Aadhaar](/ˈɑːdɑːɹ/)",
    "Veilgate": "[Veilgate](/vˈeɪlɡeɪt/)",
    "denied": "[denied](/dɪnˈaɪd/)",
    "poisoned": "[poisoned](/pˈɔɪzənd/)",
}


def speakable(text: str) -> str:
    for word, ipa in SAY.items():
        text = text.replace(word, ipa)
    return text


def sh(*args: str) -> None:
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def video_length(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(r.stdout)


def main() -> None:
    src = OUT / "veilgate-demo.mp4"
    if not src.exists():
        sys.exit(f"missing {src}; record the video first")
    total = video_length(src)
    WORK.mkdir(parents=True, exist_ok=True)
    tts = KPipeline(lang_code="a")

    clips: list[tuple[float, Path, str]] = []
    report = []
    for i, (start, text) in enumerate(LINES):
        wav = WORK / f"line{i:02d}.wav"
        audio = np.concatenate([np.asarray(a) for _, _, a in tts(speakable(text), voice=VOICE, speed=SPEED)])
        sf.write(wav, audio, 24000)
        window = (LINES[i + 1][0] if i + 1 < len(LINES) else total) - start - 0.25
        d = duration(wav)
        if d > window:
            tempo = min(d / window, 1.3)
            fast = WORK / f"line{i:02d}-fit.wav"
            sh("ffmpeg", "-y", "-i", str(wav), "-filter:a", f"atempo={tempo:.3f}", str(fast))
            wav, d2 = fast, duration(fast)
            report.append(f"line {i:02d} at {start:5.1f}s: {d:.1f}s in a {window:.1f}s window -> sped up x{tempo:.2f}" + ("" if d2 <= window else f" (still {d2 - window:.1f}s over)"))
        clips.append((start, wav, text))

    # lay every clip at its start time, then even out the loudness
    inputs, chains = [], []
    for k, (start, wav, _) in enumerate(clips):
        inputs += ["-i", str(wav)]
        chains.append(f"[{k}:a]adelay={int(start * 1000)}|{int(start * 1000)},apad[a{k}]")
    mix = "".join(f"[a{k}]" for k in range(len(clips)))
    graph = ";".join(chains) + f";{mix}amix=inputs={len(clips)}:normalize=0:duration=longest,atrim=0:{total:.2f},loudnorm=I=-16:TP=-1.5:LRA=9[voice]"
    narration = OUT / "narration.wav"
    sh("ffmpeg", "-y", *inputs, "-filter_complex", graph, "-map", "[voice]", "-ar", "44100", str(narration))

    for name in ("veilgate-demo", "veilgate-demo-clean"):
        video = OUT / f"{name}.mp4"
        if video.exists():
            out = OUT / f"{name.replace('veilgate-demo', 'veilgate-demo-voiced')}.mp4"
            sh("ffmpeg", "-y", "-i", str(video), "-i", str(narration), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out))
            print("wrote", out)
    print(f"voice={VOICE} speed={SPEED}; {len(clips)} lines, video {total:.1f}s")
    print("\n".join(report) or "every line fit its window without speeding up")


if __name__ == "__main__":
    main()
