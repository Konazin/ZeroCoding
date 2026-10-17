"""Probe how Ornith (or any llama-server build) reacts to per-request thinking controls.

Prints total output tokens, hidden reasoning size and latency for: default, enable_thinking=false,
reasoning_effort=none and reasoning_budget_tokens. See docs/RESEARCH-effort.md. Needs a running llama-server.
"""
import json, time, urllib.request
URL="http://127.0.0.1:8080/v1/chat/completions"
PROMPT="Write a Python function that returns the n-th prime number and say in one sentence what its complexity is."
def call(extra, label, max_tokens=1500):
    body={"model":"ornith-1.5-9b-q5-k-m","messages":[{"role":"user","content":PROMPT}],"max_tokens":max_tokens,"temperature":0.6,"stream":False}
    body.update(extra)
    t=time.time()
    try:
        r=json.load(urllib.request.urlopen(urllib.request.Request(URL,json.dumps(body).encode(),{"Content-Type":"application/json"}),timeout=300))
    except Exception as e:
        print(f"{label:34} ERROR {e}"); return
    m=r["choices"][0]["message"]; u=r["usage"]
    print(f"{label:34} total_out={u['completion_tokens']:5} think_chars={len(m.get('reasoning_content') or ''):5} answer_chars={len(m.get('content') or ''):5} finish={r['choices'][0]['finish_reason']:6} {time.time()-t:5.1f}s")
TAGS={"reasoning_budget_start_tag":"<think>","reasoning_budget_end_tag":"</think>","reasoning_budget_message":"Enough thinking, answering now."}
call({}, "default (thinks)")
call({"chat_template_kwargs":{"enable_thinking":False}}, "enable_thinking=false")
call({"reasoning_effort":"none"}, "reasoning_effort=none")
call({"reasoning_budget_tokens":128, **TAGS}, "reasoning_budget_tokens=128")
call({"reasoning_budget_tokens":512, **TAGS}, "reasoning_budget_tokens=512")
call({"reasoning_budget_tokens":128}, "budget=128 (no tags given)")
call({}, "default, max_tokens=300 (old Low)", max_tokens=300)
