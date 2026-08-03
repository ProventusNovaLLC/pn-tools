# skills/

Interactive debugging guides for AI assistants (Claude Skills). Each
skill walks one of the ProventusNova debugging methods step by step —
asking about your hardware, guiding the checks, branching on results.

Planned (in build order):

| Skill | Method it walks | Status |
|---|---|---|
| `camera-bringup-debug` | Camera bring-up isolation: from "zero frames" to the broken layer (NVIDIA Jetson, directly-wired CSI) | built, in engineering review |
| `boot-stage-id` | Boot-stage identification: paste a boot log, find which stage died (Jetson + Genio marker tables) | planned |
| `gmsl-debug` | GMSL2 link bisection: deserializer pattern → serializer pattern → live camera | planned |

Skills are published here as they pass engineering review. The written
SOPs behind each method live at
[proventusnova.com/blog](https://proventusnova.com/blog).
