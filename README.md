# Sprout

**What can I plant right now?**

A planting calendar that works the answer out from frost dates, then explains
itself in plain language using an open-weight model running on your own machine.

```
==================================================================
  Sprout - Friday 09 October 2026
  North India - Delhi, Punjab, Haryana
  first frost expected 20 November  (42 days away)
==================================================================

Sow now
  Broad beans   direct          to -4C    (window closes 11 Oct)
  Peas          direct          to -3C    (window closes 16 Oct)
  Spinach       direct          to -6C    (window closes 15 Nov)
  Kale          direct          to -10C   (window closes 20 Nov)
  ...
```

Then one or two sentences of advice, and a suggested next question.

## Why this exists

Planting calendars online either want you to create an account, or they make you
pick a location from a dropdown and then show you an advert. Frost dates are not
complicated: most cool-season vegetables are timed backwards from the day you
expect frost. That is arithmetic, and arithmetic belongs in code, not in a web
form.

So Sprout does the arithmetic, shows it to you plainly, and stops. The screen is
the shortest part of the experience. Then you go outside and plant something.

## Install

You need [Ollama](https://ollama.com) and a model.

```bash
ollama serve
ollama pull qwen2.5:3b
```

No `pip install`. Sprout uses only the Python standard library, so there is
nothing to install, nothing to break, and no virtualenv.

## Run

```bash
./run.sh                                  # today, your region
./run.sh --region uk
./run.sh --ask "why not sow peas?"
./run.sh --chat                           # ask follow-up questions
./run.sh --no-ai                          # facts only, instant, no model
./run.sh --list                           # show every region
```

| Flag | Default | Meaning |
|---|---|---|
| `--region` | `north-india` | one of 7 regions, see `--list` |
| `--first-frost` | from region | override as `MM-DD`, e.g. `11-05` |
| `--date` | today | pretend today is this, `YYYY-MM-DD` |
| `--ask` | | ask one question and exit |
| `--chat` | | interactive questions |
| `--no-ai` | off | skip the model, print the computed plan only |
| `--model` | `qwen2.5:3b` | any Ollama model |

## How it works

The same lesson LingoBuddy taught, applied to gardening: **use the model for the
fuzzy part, use code for the exact part.**

**The dates are computed, not generated.** Every crop has a sowing window measured
in days relative to the first expected frost (`spinach: -60 to -5`, meaning sow
anywhere from 60 days before frost until 5 days before it). Each region has an
approximate first-frost date. Deciding what is open today is then a date
comparison — deterministic, instant, and identical every time you run it.

**The model only explains.** It is handed the region, the frost date, and the
guide notes attached to the crops that are currently open. Those notes are real
horticultural knowledge a 3B model would not reliably have, so it has something
to add rather than something to echo.

That distinction matters. My first version handed the model the whole computed
crop list and told it not to repeat it, and it repeated it anyway. Feeding it only
what it could not know already fixed that.

**Answers stay grounded.** `--ask` passes the same three computed lists, plus an
explicit instruction never to advise sowing a crop the lists show is not open.
Without that, asking *"why not sow tomatoes now?"* produced *"Sow tomatoes now"* —
the model had no grounding and simply agreed. With it, the answer is that
tomatoes are not open this season, here is what is.

## Check it works

```bash
./selftest.sh          # 11 checks end to end, about 40 seconds
./selftest.sh --quick  # skip the live model calls, about 3 seconds
```

Two of those checks exist because they caught real bugs:

- **Frost date roll-forward.** Melbourne's first frost is in April. On an October
  date the naive code produced *"first frost expected 25 April (-167 days away)"*
  and marked every crop as finished. Southern hemisphere dates now roll forward to
  the correct year.
- **Out-of-season questions.** The hallucinated-tomato case above, kept as a
  regression test so it cannot come back.

The window boundary check verifies that the first and last day of every sowing
window count as open, and the days either side do not.

## Limitations

- **Frost dates are regional averages**, not a forecast, and are deliberately
  rounded. Use `--first-frost` if you know better for your own garden.
- **Cool-season crops only.** Tomatoes, peppers and aubergines are timed against
  the *last* frost and are out of scope here.
- The AI explains and answers questions. It does not decide anything — every date
  in the plan comes from the code.
- Terminal only.

## Licence

MIT. Model weights are Alibaba's Qwen, distributed under the Apache 2.0 licence.