# skills/

Interactive debugging guides for AI assistants (Claude Skills). Each
skill walks one of the ProventusNova debugging methods step by step —
asking about your hardware, guiding the checks, branching on results.

Planned (in build order):

| Skill | Method it walks |
|---|---|
| `camera-bringup-debug` | Camera bring-up isolation: from "zero frames" to the broken layer (Jetson Argus / Genio camsys) |
| `boot-stage-id` | Boot-stage identification: paste a boot log, find which stage died (Jetson + Genio marker tables) |
| `gmsl-debug` | GMSL2 link bisection: deserializer pattern → serializer pattern → live camera |

Skills are published here as they pass engineering review. The written
SOPs behind each method live at
[proventusnova.com/blog](https://proventusnova.com/blog).
