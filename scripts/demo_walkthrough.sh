#!/usr/bin/env bash
# End-to-end demo walkthrough against the live stack.
set -e
API=http://localhost:8000
login() { curl -s -X POST $API/api/v1/auth/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"$1\",\"password\":\"Demo@12345\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])"; }

echo "== 1. Login all roles =="
for u in admin manager reviewer management assessor owner-alpha owner-beta owner-eps; do
  T=$(login $u@example.local)
  echo "  $u: ${T:0:20}... OK"
done
OWNER=$(login owner-alpha@example.local); REVIEWER=$(login reviewer@example.local)
MGR=$(login manager@example.local); BETA_OWNER=$(login owner-beta@example.local)
AO=$(login owner-alpha@example.local)

ids() { docker compose exec -T backend python -c "
from app.db.session import SessionLocal
from app.models import ReportingPeriod, Entity
from sqlalchemy import select
with SessionLocal() as db:
    p = db.scalar(select(ReportingPeriod).where(ReportingPeriod.label=='FY2025-26'))
    a = db.scalar(select(Entity).where(Entity.name=='Plant Alpha'))
    b = db.scalar(select(Entity).where(Entity.name=='Plant Beta'))
    g = db.scalar(select(Entity).where(Entity.name=='MEIL Group'))
    print(p.id, a.id, b.id, g.id)"; }
read PERIOD ALPHA BETA GROUP <<< $(ids)

echo "== 2. Owner submits energy 170,000 kWh (demo anomaly #2) =="
AID=$(curl -s "$API/api/v1/assignments?entity_id=$ALPHA&status=IN_PROGRESS" -H "Authorization: Bearer $AO" | python3 -c "
import sys,json;print(next(a['id'] for a in json.load(sys.stdin) if a['metric_code']=='C-P6-GRID-NONRENEWABLE-MWH'))")
V=$(curl -s "$API/api/v1/assignments/$AID" -H "Authorization: Bearer $AO" | python3 -c "import sys,json;print(json.load(sys.stdin)['latest_version'])")
R=$(curl -s -X POST "$API/api/v1/assignments/$AID/value" -H "Authorization: Bearer $AO" -H 'Content-Type: application/json' \
  -d "{\"action\":\"SUBMIT\",\"raw_value\":170000,\"raw_unit\":\"kWh\",\"expected_last_version\":$V}")
echo "  submit: $(echo $R | python3 -c "import sys,json;d=json.load(sys.stdin);print(f\"raw={d['raw_value']} {d['raw_unit']} -> normalized={d['normalized_value']} {d['normalized_unit']}\")")"

echo "== 3. Reviewer opens review -> YoY +70% warning appears =="
curl -s -X POST "$API/api/v1/assignments/$AID/review" -H "Authorization: Bearer $REVIEWER" -H 'Content-Type: application/json' -d '{"action":"START_REVIEW"}' > /dev/null
curl -s "$API/api/v1/validation/exceptions?entity_id=$ALPHA" -H "Authorization: Bearer $REVIEWER" | python3 -c "
import sys,json
rows=[e for e in json.load(sys.stdin) if e['rule_code']=='VR-YOY-ENERGY']
print('  YoY warning:', rows[0]['message'] if rows else 'MISSING!')"

echo "== 4. BRSR Core metric without evidence: approval is BLOCKED =="
WID=$(curl -s "$API/api/v1/assignments?entity_id=$ALPHA&status=IN_PROGRESS" -H "Authorization: Bearer $AO" | python3 -c "
import sys,json;print(next(a['id'] for a in json.load(sys.stdin) if a['metric_code']=='C-P6-WATER-WITHDRAWAL'))")
WV=$(curl -s "$API/api/v1/assignments/$WID" -H "Authorization: Bearer $AO" | python3 -c "import sys,json;print(json.load(sys.stdin)['latest_version'])")
curl -s -X POST "$API/api/v1/assignments/$WID/value" -H "Authorization: Bearer $AO" -H 'Content-Type: application/json' \
  -d '{"action":"SUBMIT","raw_value":5400,"raw_unit":"kL","expected_last_version":'"$WV"'}' > /dev/null
curl -s -X POST "$API/api/v1/assignments/$WID/review" -H "Authorization: Bearer $REVIEWER" -H 'Content-Type: application/json' -d '{"action":"START_REVIEW"}' > /dev/null
R=$(curl -s -X POST "$API/api/v1/assignments/$WID/review" -H "Authorization: Bearer $REVIEWER" -H 'Content-Type: application/json' -d '{"action":"APPROVE"}')
echo "  approve without evidence: $(echo $R | python3 -c "import sys,json;print(json.load(sys.stdin).get('detail','UNEXPECTED SUCCESS'))")"

echo "== 5. Owner uploads evidence; re-run clears BLOCKING; approval succeeds =="
WVID=$(curl -s "$API/api/v1/assignments/$WID" -H "Authorization: Bearer $AO" | python3 -c "import sys,json;print(json.load(sys.stdin)['values'][0]['id'])")
UP=$(curl -s -X POST "$API/api/v1/evidence?metric_value_id=$WVID" -H "Authorization: Bearer $AO" -F "file=@/tmp/water_meter_log.pdf;type=application/pdf")
echo "  upload: $(echo $UP | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['original_filename'], d['size_bytes'],'bytes, sha256', d['sha256_hash'][:16]+'...')")"
curl -s -X POST "$API/api/v1/validation/run" -H "Authorization: Bearer $MGR" -H 'Content-Type: application/json' -d "{\"period_id\":\"$PERIOD\",\"entity_id\":\"$ALPHA\"}" > /dev/null
R=$(curl -s -X POST "$API/api/v1/assignments/$WID/review" -H "Authorization: Bearer $REVIEWER" -H 'Content-Type: application/json' -d '{"action":"APPROVE"}')
echo "  approve after evidence: $(echo $R | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('status') or 'BLOCKED: '+d.get('detail','?'))")"

echo "== 6. Owner explains Beta workforce mismatch (demo anomaly #1); reviewer resolves =="
curl -s -X POST "$API/api/v1/validation/run" -H "Authorization: Bearer $MGR" -H 'Content-Type: application/json' -d "{\"period_id\":\"$PERIOD\",\"entity_id\":\"$BETA\"}" > /dev/null
EX=$(curl -s "$API/api/v1/validation/exceptions?entity_id=$BETA&status=OPEN" -H "Authorization: Bearer $REVIEWER" | python3 -c "
import sys,json
rows=[e for e in json.load(sys.stdin) if 'reconcile' in e['message']]
print(rows[0]['id'] if rows else '')")
MSG=$(curl -s "$API/api/v1/validation/exceptions?entity_id=$BETA&status=OPEN" -H "Authorization: Bearer $REVIEWER" | python3 -c "
import sys,json
rows=[e for e in json.load(sys.stdin) if 'reconcile' in e['message']]
print(rows[0]['message'][:110] if rows else 'MISSING')")
echo "  exception: $MSG"
curl -s -X POST "$API/api/v1/validation/exceptions/$EX/explain" -H "Authorization: Bearer $BETA_OWNER" -H 'Content-Type: application/json' -d '{"explanation":"Contract staff acquired mid-year; HRIS reconciliation pending."}' | python3 -c "import sys,json;print('  explained ->', json.load(sys.stdin)['status'])"
curl -s -X POST "$API/api/v1/validation/exceptions/$EX/resolve" -H "Authorization: Bearer $REVIEWER" | python3 -c "import sys,json;print('  resolved  ->', json.load(sys.stdin)['status'])"

echo "== 7. RBAC negatives =="
R=$(curl -s "$API/api/v1/entities/$BETA" -H "Authorization: Bearer $AO")
echo "  owner-alpha reads Plant Beta: $(echo $R | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('detail','LEAK!'))")"
R=$(curl -s -X POST "$API/api/v1/assignments/$AID/value" -H "Authorization: Bearer $(login management@example.local)" -H 'Content-Type: application/json' -d '{"action":"SAVE_DRAFT","raw_value":1}')
echo "  management writes value: $(echo $R | python3 -c "import sys,json;print(json.load(sys.stdin).get('detail','LEAK!'))")"

echo "== 8. Calculations for Alpha (derived metrics) =="
curl -s -X POST "$API/api/v1/calculations/run" -H "Authorization: Bearer $MGR" -H 'Content-Type: application/json' -d "{\"period_id\":\"$PERIOD\",\"entity_id\":\"$ALPHA\"}" | python3 -c "import sys,json;d=json.load(sys.stdin);print('  computed:', d['computed'], '| skipped (already current):', d['skipped'], '| failures:', len(d['failures']))"

echo "== 9. Consolidation: FY24 group totals + ratio math =="
FY24=$(docker compose exec -T backend python -c "
from app.db.session import SessionLocal
from app.models import ReportingPeriod
from sqlalchemy import select
with SessionLocal() as db:
    print(db.scalar(select(ReportingPeriod).where(ReportingPeriod.label=='FY2024-25')).id)")
curl -s -X POST "$API/api/v1/consolidation/recompute" -H "Authorization: Bearer $MGR" -H 'Content-Type: application/json' -d "{\"period_id\":\"$FY24\",\"metric_code\":\"C-P6-TOTAL-ENERGY\"}" > /dev/null
curl -s -X POST "$API/api/v1/consolidation/recompute" -H "Authorization: Bearer $MGR" -H 'Content-Type: application/json' -d "{\"period_id\":\"$FY24\",\"metric_code\":\"C-P6-GHG-INTENSITY\"}" > /dev/null
curl -s "$API/api/v1/consolidation/$GROUP/C-P6-TOTAL-ENERGY/$FY24" -H "Authorization: Bearer $MGR" | python3 -c "
import sys,json;d=json.load(sys.stdin)
print(f\"  Group FY24 energy: {d['computed_value']} {d['unit']} from {d['contributing_value_count']} values (stale={d['is_stale']})\")"
curl -s "$API/api/v1/consolidation/$GROUP/C-P6-GHG-INTENSITY/$FY24" -H "Authorization: Bearer $MGR" | python3 -c "
import sys,json;d=json.load(sys.stdin)
print(f\"  Group FY24 GHG intensity: {d['computed_value']} {d['unit']} (Σnum/Σden, not averaged)\")"

echo "== 10. Frontend pages =="
for p in /login /assignments /review /exceptions /consolidation /framework /entities; do
  printf "  %-16s %s\n" $p $(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000$p)
done
echo "== WALKTHROUGH COMPLETE =="
