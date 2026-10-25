"""Build web/usecases.html: a self-contained static page. Demo frames are produced by the real pipeline,
so the page cannot drift from what the Co-Pilot actually extracts.

    python scripts/build_usecases.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from copilot.audit import AuditLog  # noqa: E402
from copilot.cad import MockCAD  # noqa: E402
from copilot.models import Segment  # noqa: E402
from copilot.orchestrator import Orchestrator  # noqa: E402
from copilot.speech import load_scenarios  # noqa: E402

KEYS = ("incident_type", "priority", "location", "region", "address_detail", "persons", "ages", "injuries", "hazards")


def frames_for(orch: Orchestrator, sc: dict) -> list[dict]:
    cid = "DEMO-" + sc["id"]
    st = orch.start_call(cid, sc.get("caller_number"), sc.get("aml"), sc["id"])
    out = []
    for turn in sc["turns"]:
        orch.ingest(Segment(call_id=cid, speaker=turn["speaker"], text=turn["text"], final=True, confidence=turn.get("confidence", 0.92)))
        case = orch.case(st)
        q = st.next_question
        out.append({
            "speaker": turn["speaker"], "text": turn["text"], "lowq": turn.get("confidence", 1) < 0.7,
            "cues": [{"id": c.id, "label": c.label, "level": c.level, "evidence": c.evidence} for c in st.cues.values()],
            "fields": {k: {"label": st.fields[k].label, "value": str(st.fields[k].value), "conf": st.fields[k].confidence} for k in KEYS if k in st.fields},
            "priority": {"level": st.severity.level, "score": st.severity.score, "reasons": [f"{r.label} +{r.points}" for r in st.severity.reasons]},
            "next": {"en": q["en"], "ar": q["ar"]} if q else None,
            "lang": f"{st.lang}{'/' + st.dialect if st.dialect else ''}{' · code-switched' if st.code_switched else ''}",
            "checklist": [{"q": i.question["en"], "done": i.done} for i in st.checklist],
            "case": {"number": case["case_number"], "region": (case.get("location") or {}).get("region"), "area": (case.get("location") or {}).get("area"),
                     "agencies": case.get("agencies", []), "facilities": [{"name": f["name"], "kind": f["kind"], "km": f["distance_km"]} for f in case.get("facilities", [])]},
        })
    return out


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    orch = Orchestrator(AuditLog(tmp / "a.jsonl"), MockCAD(tmp / "c"))
    scen = load_scenarios()
    data = {
        "scenarios": {sid: {"id": sid, "title": sc["title"], "aml": sc.get("aml"), "frames": frames_for(orch, sc)} for sid, sc in scen.items()},
        "places": [{k: e[k] for k in ("name", "name_ar", "type", "lat", "lon", "region")} for e in orch.location.gaz.entries],
        "facilities": orch.ref.facilities, "regions": orch.ref.regions,
    }
    tpl = (ROOT / "web" / "usecases.template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    (ROOT / "web" / "usecases.html").write_text(html, encoding="utf-8")
    print(f"web/usecases.html written ({len(html) // 1024} KB, {len(data['scenarios'])} scenarios)")


if __name__ == "__main__":
    main()
