from faster_whisper import WhisperModel
import json
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True, help="Path to WAV file")
parser.add_argument("--output", required=True, help="Path to output JSON")
args = parser.parse_args()

model = WhisperModel(
    "base",
    compute_type="int8"
)

segments, info = model.transcribe(
    args.input,
    beam_size=5
)

output = []
for s in segments:
    output.append({
        "start": round(s.start, 2),
        "end": round(s.end, 2),
        "text": s.text.strip()
    })

with open(args.output, "w") as f:
    json.dump(output, f, indent=2)

print(f"Wrote {len(output)} segments to {args.output}")
