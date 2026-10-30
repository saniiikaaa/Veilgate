# Feedback on Nebius Token Factory and NVIDIA Nemotron

Written while building Veilgate for the Nebius x NVIDIA Global AI Hackathon.

**What worked well**
- The OpenAI-compatible API meant our gateway was a thin wrapper: base URL, key, model id. Switching between Token Factory and a self-hosted server was a one-line config change.
- `GET /models` made it easy to find the exact Nemotron ids on our account (Nano 30B, Super 120B, Ultra 550B). All three answered in roughly one second for short prompts.
- Nemotron followed a strict "reply with JSON only" instruction well enough to act as a privacy judge over already-masked text.

**What we ran into**
- Nemotron is a reasoning model. With a small `max_tokens` it can spend the entire budget thinking and return an empty `content` (finish reason `length`). We handle this by retrying once with a larger budget. A documented, per-request way to cap or disable reasoning would help, as would returning reasoning separately and not counting it against the visible answer.
- Model ids are mixed case (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` vs `nvidia/nemotron-3-super-120b-a12b`). A short list of recommended ids per use case in the quickstart would save guessing.
- Our first guesses for model ids (from older naming) did not exist; the error message for an unknown model could suggest close matches.

**Where Token Factory helped most**
- Fast, cheap Nano calls for the per-hook judge kept the extra latency small while still giving a real second opinion on names and prompt injection.
