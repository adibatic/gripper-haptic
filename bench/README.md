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

## 2. Is the EM drive really an H-bridge?

Chapter 3 and the README both describe the EM channels as bistable pins on
an H-bridge, with `IN1`/`IN2` pushing current either way. That claim should
be verified before it goes into a submitted thesis. There are two checks and
they answer different questions.

### Step 1 — what part is on the board

Look at the driver board between the ESP32 and the coil.

- If a wire runs **straight from a GPIO to the coil** with no chip in
  between, there is no bridge. Stop here.
- If there is a small IC, read its top marking under a phone macro shot and
  look up the datasheet. Parts common at this scale: **DRV8833**,
  **TB6612FNG**, **DRV8871**, **AT8236**, **L293D**. Four discrete MOSFETs in
  an H pattern is also a real bridge.
- Check the marking actually maps to a **dual-channel, bidirectional** part.
  A single-channel or unidirectional driver will not do what the firmware
  assumes.

Two details from the firmware are worth carrying into that inspection:

- `EM_PINS` reuses exactly the pins in `MOTOR_PWM_PINS` and `MOTOR_EN_PINS`.
  The EM path and the LRA path share the same driver channels.
- `ACDriver` (the LRA path) alternates `IN1`/`IN2` polarity every half period
  to make a bipolar carrier. That only produces alternating current *if a
  bridge is present*. If the LRA buzzes, something between the GPIOs and the
  coil is reversing polarity.
- `NSLEEP_PIN = 19` implies a driver IC with a sleep or standby input.
  DRV8833 (`nSLEEP`) and TB6612FNG (`STBY`) both have one. Two pins per
  channel plus one sleep pin fits **DRV8833** more closely than TB6612FNG,
  which needs three pins per channel.

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

| Observation | What to write |
| --- | --- |
| Both directions move the pin, oppositely | H-bridge confirmed. Current wording stands. |
| Only one direction moves it; the pin must be pushed back by hand | Not an H-bridge in practice. Describe it as a **single-direction pulsed solenoid with a mechanical return**, and drop "bistable" unless the pin genuinely holds position unpowered. |
| Only one direction moves it, but the pin *stays* where it was put | Latching is real, drive is not bidirectional. Describe as a **latching pin driven by unidirectional pulses**. |
| Nothing moves on the channel you tested | Wrong channel, or that channel is unsoldered. Re-run with `CHANNEL` set to the other one. |

Note that step 2 alone cannot separate "no bridge fitted" from "bridge fitted
but one half is dead or unwired". Only step 1 distinguishes those. The
distinction matters for the wording, because a populated bridge with a
broken leg is a fault, whereas no bridge at all is a design difference.

### The second, unsoldered board

The most likely explanation, from the pin map rather than from looking at it:

`EM_PINS` defines five channels. If each board carries a **dual** H-bridge,
which is what DRV8833 and TB6612FNG both are, then one board serves two
channels. The study used exactly two, thumb and index, which
`firmware/stream.py` maps to `THUMB, INDEX = (0, 1)` on a right-hand mount,
that is channels T1 and T2. Those are the first two entries of `EM_PINS`.

So a single soldered board carrying T1 and T2 covers everything the study
needed, and a second board would extend the array to T3 and T4 without being
required. That is consistent with the array being built for five channels and
wired for two.

To confirm rather than infer: check whether the soldered board's inputs go to
GPIO 20/21 and 14/15 (T1 and T2). If they do, the reading above is right. If
the second board is wired to the same pins, or to none, it is a spare rather
than an extension.

A left-hand mount would break this, since `stream.py` maps left-hand
thumb/index to channels 4 and 3, which would sit on different boards.
