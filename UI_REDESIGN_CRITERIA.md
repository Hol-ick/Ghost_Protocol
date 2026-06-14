# Ghost Protocol UI Redesign Criteria

## Design Sources

- User-provided Corporate Trust prompt: use slate-white surfaces, indigo-to-violet gradients, soft colored shadows, rounded enterprise cards, and clear accessible focus states.
- `https://github.com/anthropics/skills`: treat each UI region like a skill. It must expose only the resource and action needed for the current task, while raw details stay hidden until requested.

## Non-Negotiables

- Do not rebuild the old three-panel flow with different colors.
- Do not show unused writing controls on the default screen. Tone and length remain internal defaults unless the user explicitly asks for them back.
- Do not place logs at the bottom as a permanent block. Runtime logs live next to the active operation and stay compact.
- Do not show empty preview or placeholder guidance panels before work exists.
- Do not use legacy labels such as `PAYLOAD`, `LAUNCH`, or step jargon that does not match the user's actual workflow.

## Default Screen

- Show a process rail: board reading, draft writing, review, publish.
- Show one command sheet with only the recurring inputs: gallery id, gallery type, read depth, topic, draft count.
- Keep the default screen within one viewport when there are no results.
- Put recent/manage actions in a secondary surface, not in the main command path.

## Result Screen

- The briefing appears as a compact decision card with one primary action: use it as the topic.
- Raw rows, charts, and full source data stay inside a detail popover/expander.
- Draft review uses compact cards sized for quick scanning, not long stretched horizontal panels.
- Publish progress shows only status, latest activity, and the current preview unless the user opens logs.

## Visual System

- Base: slate-white background, white raised surfaces, indigo/violet accents, readable slate text.
- Shape: rounded SaaS cards, soft colored shadows, subtle lifted interactions.
- Typography: friendly geometric sans for UI and headings, mono only for labels and counters.
- Motion and decoration should not compete with the job: read, write, choose, publish.
