# boot-logs/

Known-good boot logs from devkits we physically own, captured over
serial console and stamped with the exact software release. Use them to
triage by diff: capture your board's log, find the last marker line that
matches the known-good log, and you've identified the failing boot stage.

Layout (populated as captures pass sanitization review):

```
boot-logs/
  jetson/   # per-devkit, per-JetPack release
  genio/    # per-EVK, per-IoT-Yocto release
```

Each log's header comment records: board, module, software release,
capture date, and capture command. Logs are sanitized (no serial
numbers, no MACs, no client identifiers) before publication.

The annotated versions — stage boundaries marked, with the triage-by-diff
method guide — ship with the Boot Debug Starter Packs at
[proventusnova.com/blog](https://proventusnova.com/blog).
