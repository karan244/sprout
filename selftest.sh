#!/usr/bin/env bash
# Sprout self-test. Cheapest checks first.
#   ./selftest.sh          full run, about 40 seconds
#   ./selftest.sh --quick  skip the live model calls, about 3 seconds

set -u
cd "$(dirname "$0")"

QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

PASS=0; FAIL=0
ok()   { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
head_() { echo; echo "== $1"; }

BRIDGE="${LINGOBUDDY_HOST:-http://172.29.192.1:11434}"

head_ "1. Python"
command -v python3 >/dev/null 2>&1 \
  && ok "python3 present ($(python3 --version 2>&1))" \
  || bad "python3 missing"

head_ "2. Source files"
for f in sprout.py run.sh README.md; do
  [ -f "$f" ] && ok "$f present" || bad "$f missing"
done

head_ "3. Syntax"
if python3 -m py_compile sprout.py 2>/dev/null; then
  ok "sprout.py compiles"
else
  bad "sprout.py has a syntax error"; python3 -m py_compile sprout.py
fi
rm -rf __pycache__

head_ "4. Ollama server"
if curl -s --max-time 5 "$BRIDGE/api/version" >/dev/null 2>&1; then
  ok "reachable at $BRIDGE ($(curl -s --max-time 5 "$BRIDGE/api/version"))"
else
  bad "cannot reach Ollama at $BRIDGE"
fi

head_ "5. Models"
MODELS=$(curl -s --max-time 8 "$BRIDGE/api/tags" 2>/dev/null \
         | python3 -c "import sys,json;print(' '.join(m['name'] for m in json.load(sys.stdin).get('models',[])))" 2>/dev/null)
[ -n "${MODELS:-}" ] && ok "pulled: $MODELS" || bad "no models pulled"
MODEL=$(printf '%s\n' $MODELS | grep -m1 -E 'qwen2.5:3b|gemma3:4b' || true)
[ -n "$MODEL" ] && ok "will use: $MODEL" || bad "no suitable model (need qwen2.5:3b or gemma3:4b)"

head_ "6. Frost date roll-forward (southern hemisphere regression)"
ROLL=$(python3 -c "
import sprout
from datetime import date
bad = []
# Northern hemisphere: an October date is still ahead in October.
f = sprout.md_to_date(11, 20, date(2026, 10, 9))
if f != date(2026, 11, 20): bad.append('northern roll-forward wrong: ' + str(f))
# Southern hemisphere: April frost must roll to NEXT year when today is October.
f = sprout.md_to_date(4, 25, date(2026, 10, 9))
if f != date(2027, 4, 25): bad.append('southern roll-forward wrong: ' + str(f))
if (f - date(2026,10,9)).days <= 0: bad.append('southern frost is not in the future')
# A date later today must not roll.
f = sprout.md_to_date(12, 1, date(2026, 10, 9))
if f != date(2026, 12, 1): bad.append('should not have rolled: ' + str(f))
print('ROLL_OK' if not bad else 'ROLL_BAD: ' + '; '.join(bad))
" 2>&1)
echo "$ROLL" | grep -q ROLL_OK && ok "frost dates always land in the future" || bad "$ROLL"

head_ "7. Sowing window boundaries"
WIN=$(python3 -c "
import sprout
from datetime import date
bad = []
frost = date(2026, 11, 20)
spinach = [c for c in sprout.CROPS if c['name'] == 'Spinach'][0]
early, late = spinach['window']
start = sprout.sow_window(spinach, frost)[0]
end   = sprout.sow_window(spinach, frost)[1]
# First and last day of the window must count as SOW NOW.
for probe, want in [(start, 'SOW NOW'), (end, 'SOW NOW'),
                    (start.toordinal()-1 and date.fromordinal(start.toordinal()-1), 'WAIT'),
                    (date.fromordinal(end.toordinal()+1), 'DONE')]:
    got = sprout.plan_for(probe, frost, [spinach])[0]['status']
    if got != want: bad.append('%s expected %s got %s' % (probe, want, got))
print('WIN_OK' if not bad else 'WIN_BAD: ' + '; '.join(bad))
" 2>&1)
echo "$WIN" | grep -q WIN_OK && ok "window edges are inclusive and correct" || bad "$WIN"

head_ "8. Region data sanity"
REG=$(python3 -c "
import sprout
bad = []
for key, r in sprout.REGIONS.items():
    mm, dd = r['first_frost']
    if not (1 <= mm <= 12): bad.append(key + ' month out of range')
    if not (1 <= dd <= 31): bad.append(key + ' day out of range')
    if not r.get('label'): bad.append(key + ' has no label')
for c in sprout.CROPS:
    e, l = c['window']
    if l < e: bad.append(c['name'] + ' window ends before it starts')
    if not (c['hardy'] <= 0): bad.append(c['name'] + ' hardiness should be at or below freezing')
print('REG_OK' if not bad else 'REG_BAD: ' + '; '.join(bad))
" 2>&1)
echo "$REG" | grep -q REG_OK \
  && ok "$(python3 -c 'import sprout; print(str(len(sprout.REGIONS)) + " regions and " + str(len(sprout.CROPS)) + " crops have valid data")' 2>/dev/null)" \
  || bad "$REG"

if [ "$QUICK" = "1" ]; then
  head_ "9-10. Live model calls"
  echo "  SKIPPED (--quick)"
else
  head_ "9. Live plan + AI explanation"
  OUT=$(timeout 300 python3 sprout.py --region north-india 2>&1)
  if echo "$OUT" | grep -q "first frost expected"; then
    ok "printed a plan"
  else
    bad "no plan printed"; echo "$OUT" | tail -5 | sed 's/^/      /'
  fi
  if echo "$OUT" | grep -q "NEXT:"; then
    ok "AI gave advice and a follow-up question"
  else
    bad "AI section missing NEXT: marker"
  fi
  if echo "$OUT" | grep -qE '^\s*[-*]\s'; then
    bad "AI used bullet points despite being told not to"
  else
    ok "AI kept to plain sentences"
  fi

  head_ "10. Out-of-season question must not be hallucinated"
  ANS=$(timeout 300 python3 sprout.py --region north-india --ask "why not sow tomatoes now?" 2>&1)
  if echo "$ANS" | grep -qiE 'sow (your )?tomatoes now|plant (your )?tomatoes now'; then
    bad "hallucinated advice to plant an out-of-season crop"
  else
    ok "refused to advise on a crop outside the computed list"
  fi
fi

echo
echo "=============================================="
echo "  $PASS passed, $FAIL failed"
echo "=============================================="
[ "$FAIL" -eq 0 ] || exit 1