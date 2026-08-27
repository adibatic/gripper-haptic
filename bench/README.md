# Bench measurements

Two things live here, both feeding the thesis rather than the experiment
pipeline.

1. **Latency** — the measurement Section 5.7 is still missing.
2. **EM drive verification** — confirming that the hardware matches how
   Chapter 3 and the README describe it.

Neither is imported by `run/` or `analysis/`. Nothing here runs during a
study session.

---

## 1. Sensor-to-actuator latency

The loop has three stages. Two are measurable in software, one is not.

| Stage | What it covers | How |
| --- | --- | --- |
| A. Sense | camera frame → depth map → intensity | `measure_latency.py --stage sense` |
| B. Link | host serial write → coil energised | `measure_latency.py --stage link` |
| C. Actuate | coil energised → pin physically moves | oscilloscope, or `--audio` |

### Running it

Flash and start the board responder first:

```
python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
python -m mpremote connect /dev/ttyACM0 fs cp bench/board_latency_probe.py :
python -m mpremote connect /dev/ttyACM0 repl
>>> exec(open('board_latency_probe.py').read())
```

Detach with `Ctrl-X` so the port is free, then on the host:

```
python bench/measure_latency.py --stage all --n 200 --out bench/results
```

Output is median, IQR and p95 per stage, matching how Chapter 5 reports
everything else, written to `section_5_7_latency.csv`.

### Reading the link number

The board acknowledges an `E` command *at the instant it energises the coil*,
before it holds the pulse. So the round trip covers serial out, parse,
pin write, and serial back. The script also measures an echo-only baseline
(`P` → `p`, no pins touched) and reports the difference, which isolates
actuation dispatch from USB round trip.

Report the raw round trip, not the halved value. The two directions are not
symmetric and halving would understate the outbound path.

### Stage C, and why the link figure is a lower bound

Nothing in software can see the pin move. Two ways to close that gap:

- **Oscilloscope (preferred).** `board_latency_probe.py` toggles
  `TRIGGER_PIN` on a `T` command. Probe that pin and a coil lead, trigger on
  the edge, and read the delay directly. Check `TRIGGER_PIN` is not one of
  `MOTOR_PWM_PINS`, `MOTOR_EN_PINS` or `NSLEEP_PIN` before wiring anything.
- **Microphone.** The pin click is audible. `--audio` records while firing
  and reports acknowledgement-to-click delay. Cheap, but it includes acoustic
  flight time (~3 ms per metre) and a plain amplitude threshold, so quote it
  with those caveats or not at all.

Without either, the link figure is a **lower bound on end-to-end latency**,
not the end-to-end figure. Section 5.7 should say so explicitly.

Independently of all this, the haptic loop runs at 15 Hz
(`HAPTIC_HZ`, `run/experiment.py`), so a new intensity can only reach the
actuator every ~67 ms regardless of how fast any single stage is. That
sampling interval, not the per-stage latency, is likely what participants
were reporting when several described a perceived delay.

---

## 2. Is the EM drive really an H-bridge? (resolved)

Chapter 3 and the README originally described the EM channels as bistable
pins on an H-bridge, with `IN1`/`IN2` pushing current either way. That claim
has since been checked and corrected: the hardware does carry a real
per-channel H-bridge, but the firmware's control scheme never drives it
bidirectionally in practice. Both checks below contributed to that finding,
and are kept as a record of how it was reached.

### Step 1 — what part is on the board (resolved)

This was originally meant to be answered by reading the chip's top marking
under a macro photo. It has since been confirmed a more direct way, from the
board's own bill of materials: each of the five channels is driven by its own
dedicated **single-channel H-bridge motor driver IC** (one per channel, five
in total on the one board), not the dual-channel part this document
originally guessed at (DRV8833/TB6612FNG).

That changes the diagnosis. A single-channel H-bridge driver of this kind is
controlled through a **phase/enable (PH/EN) interface**, not a symmetric
`IN1`/`IN2` push-pull pair: one pin sets direction (`PH`) and the other is a
hard enable (`EN`) — pulling `EN` low disables the output entirely
(high-impedance), it does not drive current the other way. `firmware/haptic.py`
pairs each channel's old PWM pin with its EN pin and calls them `IN1`/`IN2` as
if either one alone reverses current, which is the right model for a
dual-channel push-pull part but not for a PH/EN part.

Read against the direction-check results (Step 2 below), this fully explains
what was found:

- The "engage" pulse (`IN2`: PWM-pin=0, EN-pin=1) asserts `EN` high with
  `PH` low — a genuine, enabled drive in one direction. This is why it moves
  the pin.
- The "disengage" pulse (`IN1`: PWM-pin=1, EN-pin=0) asserts `EN` **low** —
  the driver output is simply switched off, not reversed. This is why it does
  nothing, in either direction, every time it was tested.

So the chip is not missing and not faulty — it is a real, capable H-bridge per
channel that could drive both directions if commanded correctly (`EN` held
high while `PH` is toggled). The firmware's control scheme just never does
that; it only ever asserts `EN` while `PH` is at the value that gives the
"engage" direction. This is a firmware/protocol mismatch, not a hardware
defect or a missing bridge.

The shared sleep pin (`NSLEEP_PIN = 19`) is consistent with this too: a part
of this kind commonly exposes a global sleep/standby input, and one line
driving all five channels' sleep pins together matches a single shared net
across identical per-channel chips.

### Step 2 — what the hardware actually does

```
python -m mpremote connect /dev/ttyACM0 fs cp firmware/haptic.py :
python -m mpremote connect /dev/ttyACM0 fs cp bench/em_direction_check.py :
python -m mpremote connect /dev/ttyACM0 repl
>>> exec(open('em_direction_check.py').read())
```

It fires six pulses, half in each direction, in a randomised order it does
not reveal until the end, and asks after each one whether the pin moved out,
moved in, or did nothing. Hiding the order matters: knowing which direction
is coming makes it very easy to feel what you expect.

### What the outcome means for the wording

The result actually obtained — only one direction moves the pin, on both
channels tested, twice — is now explained by Step 1: a real per-channel
H-bridge exists, but the firmware's control scheme never asserts the enable
line while commanding the reverse phase, so the reverse pulse always lands as
"output disabled" rather than "output reversed". Describe the actuator's
behaviour as built and run in the study as a **single-direction pulsed
electromagnet with a passive mechanical return**, and note separately, as a
matter of root cause, that the driver hardware is capable of true bidirectional
drive and the limitation is in the firmware/pin-mapping rather than the chip.
Drop "bistable" from the actuator's description unless the pin is shown to
hold position unpowered, which was not observed.

### Step 3 — checking whether the passive return is gravity

If step 2 comes back "single direction only", one more thing is worth
checking before writing that up as a property of the actuator: repeat the
same test with the hand inverted (palm up instead of palm down). If the
single working direction stops moving the pin at all in that orientation,
gravity is doing some or all of the work in the normal orientation, not the
magnet's pull. A null result on this follow-up is not itself a conclusive
trial (it will read as "INCONCLUSIVE" from the script, since nothing moved),
so treat it as suggestive and say so, not as a second confirmed finding — but
it's worth recording either way, since it bears on whether this actuator's
behaviour would carry over to a different mounting orientation.

### The "second, unsoldered board" theory (retracted)

An earlier version of this document guessed that the five `EM_PINS` channels
might be spread across two physical boards, on the reasoning that a
dual-channel bridge part would need two boards to cover five channels, with
one board carrying the two channels (T1, T2) the study actually used and a
second board left as a spare or future extension.

Step 1's finding retracts that: each channel has its own dedicated
single-channel driver IC, and all five channels live on the one board built
for this project. There is no second board implied by the pin count, and the
earlier reasoning was built on the wrong assumption about the part (a dual
bridge) rather than what was actually populated (five single-channel bridges).
If a second board exists in the lab, it is a spare unit or an unrelated build,
not a structural extension of the five-channel array.
