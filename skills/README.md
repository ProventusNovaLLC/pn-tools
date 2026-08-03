# skills/

Interactive debugging guides for AI assistants (Claude Skills, and any
other assistant ecosystem that reads the open Agent Skills format).
Each skill walks one of the ProventusNova bench debugging methods step
by step — asking about your hardware, interpreting the command output
you paste back, branching on the result — instead of a static wall of
text you have to self-navigate.

| Skill | Debugs | Status |
|---|---|---|
| [`camera-bringup-debug`](camera-bringup-debug/) | NVIDIA Jetson camera bring-up: no `/dev/video0`, sensor missing from `i2cdetect`, capture hangs/`select timeout`, nvargus/Argus failures — directly-wired MIPI CSI sensors | available |
| `boot-stage-id` | Boot-stage identification: paste a boot log, find which stage died (Jetson + Genio marker tables) | planned |
| `gmsl-debug` | GMSL2 link bisection: deserializer pattern → serializer pattern → live camera | planned |

Install any available skill as a Claude Code plugin:

```
/plugin marketplace add ProventusNovaLLC/pn-tools
/plugin install pn-tools@pn-tools
```

Skills are published here once they pass engineering review and are
hardware-verified. The written SOPs behind each method live at
[proventusnova.com/blog](https://proventusnova.com/blog).
