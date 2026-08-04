# Chapter Interpretation — JSON only

Return **only** a JSON object (no markdown fences, no commentary) matching this schema:

```json
{
  "dialogues": [
    {"speaker_id": "id", "speaker_name": "Name", "emotion": "neutral|happy|sad|angry|fear|excited|whisper", "text": "pt-BR text"}
  ],
  "story_updates": {"characters": [{"id": "id", "name": "Name", "aliases": [], "voice_profile": {}}], "aliases": {"id": ["alias"]}}
}
```

## Speaker rules — use provided `allowed_speakers`

The user payload includes `allowed_speakers` (closed list) and text with speaker hints already resolved.

- Use **`narrator`** for narrative prose / first-person interior monologue.
- Use **character `speaker_id`** for their spoken dialogue.
- **MUST NOT** invent new speaker ids. Each dialogue has exactly one speaker.

## Output language — Brazilian Portuguese (adapted, fluent)

`dialogues[].text` MUST be natural pt-BR suitable for reading aloud.

- Rewrite freely: preserve meaning/emotion/intent, not source syntax. Match scene register.
- **Keep proper names exactly** as in source (people, places, schools, brands, titles).
- If already fluent pt-BR, keep or lightly polish.

## Rules

- `dialogues` must contain at least one item; `emotion` from the closed enum above; non-empty `text`.
- Map non-enum emotions to closest enum value. Never invent labels.
- Each dialogue must include `speaker_id` or `speaker_name`. Every speaker MUST be in `allowed_speakers`.
- `narrator` is for prose only — never a fallback for uncertain dialogue.
- `story_updates` must be minimal; prefer empty `characters`; aliases only for known ids.
- `voice_profile` is optional; provide semantic hints only (gender, age_range, pitch, pace, energy, texture, personality).

Output valid JSON only.
