import os, sys, random, collections, re
os.environ.update({"OASIS_DB": ":memory:", "OASIS_LLM": "offline", "OASIS_EXTRACT": "deterministic", "OASIS_LLM_RISK": "0",
 "OASIS_CHAT_LLM": "0", "OASIS_ML_RISK": "0", "OASIS_ANCHOR": "local", "OASIS_PASS_STUDENT": "student-demo",
 "OASIS_PASS_PARENT": "parent-demo", "OASIS_PASS_JUDGE": "judge-demo", "OASIS_RATES": "mock"})
sys.path.insert(0, sys.argv[1])
from tests.auth_helpers import new_client
st = new_client("student")
def ask(m):
    st.post("/api/reset"); j = st.post("/api/chat", json={"message": m}).json()
    return j.get("intent"), j.get("status"), j.get("money_moved"), (j.get("reply") or "")
BASE = {  # base phrase -> accepted intents
 "pay my tuition": {"pay_obligation"}, "pay my rent": {"pay_obligation"}, "what is my balance": {"balance"},
 "how much do I owe": {"obligations"}, "what is the rate today": {"rate","convert"}, "cheapest way to send 1 lakh rupees to China": {"routes"},
 "convert 20000 rupees to dollars": {"convert"}, "where is my money": {"transfer_issue","status","where"},
 "how do I build credit": {"credit"}, "tell me when the rate hits 0.075": {"rate_target"}, "cancel my payment": {"cancel"},
 "I need to pay a 200 euro fee": {"fx_bill"},
}
def typo(s):
    w=s.split(); i=random.randrange(len(w)); x=w[i]
    if len(x)>3: k=random.randrange(1,len(x)-1); x=x[:k]+x[k+1]+x[k]+x[k+2:] 
    w[i]=x; return " ".join(w)
T = {
 "upper": lambda s: s.upper(), "title": lambda s: s.title(), "nopunct_q": lambda s: s+"?", "bang": lambda s: s+"!!!",
 "please_pre": lambda s: "hey, please "+s, "pls_suf": lambda s: s+" pls", "politeness": lambda s: "Hi there, could you kindly help me: "+s+". Thanks a lot!",
 "ramble": lambda s: "so I just got to the dorm and I'm a bit stressed about everything, anyway "+s+" because my mom keeps asking",
 "typo": typo, "typo2": lambda s: typo(typo(s)), "emoji": lambda s: "💸 "+s+" 🙏", "dots": lambda s: s.replace(" ","...") if False else " ".join(s.split())+"....",
 "double_space": lambda s: s.replace(" ","  "), "lead_so": lambda s: "so, "+s, "i_want": lambda s: "i want to know: "+s, "can_you": lambda s: "can you tell me, "+s,
 "tell_me": lambda s: "tell me "+s, "need": lambda s: "I really need this: "+s, "hinglish": lambda s: "bhai "+s+" yaar",
 "txtspeak": lambda s: re.sub(r"\byou\b","u",re.sub(r"\bplease\b","pls",s)).replace("my","me").replace("what is","whats"),
 "nospace_end": lambda s: s.lower().rstrip("?."), "quotes": lambda s: '"'+s+'"', "trailing_ctx": lambda s: s+" for this semester",
 "urgent": lambda s: "URGENT!! "+s+" asap", "question_form": lambda s: "is it possible to "+s if False else "would you be able to help: "+s,
 "newline": lambda s: s.replace(" ","\n",1), "md": lambda s: "**"+s+"**", "wrong_you": lambda s: "Oasis, "+s, "bot": lambda s: "hey bot "+s,
}
random.seed(7)
tot=ok=0; dead=0; wrong=0; fails=collections.defaultdict(list); bytr=collections.defaultdict(lambda:[0,0])
for b,exp in BASE.items():
    for name,f in T.items():
        m=f(b); i,s,mv,r=ask(m); tot+=1
        good = i in exp or (i in ("unknown","clarify","help") and False)
        # pay_obligation may legitimately ask for info; accept status needs_info with same intent
        if good: ok+=1
        else:
            kind = "DEAD" if (i in ("unknown","clarify") or s in ("unknown","needs_info") and i not in exp) else "WRONG"
            if kind=="DEAD": dead+=1
            else: wrong+=1
            fails[b].append((name,m,i,s))
        bytr[name][0]+=good; bytr[name][1]+=1
print(f"METAMORPHIC {ok}/{tot} ok; dead-end {dead}; wrong-intent {wrong}")
print("\nBy transform:")
for n,(g,t) in sorted(bytr.items(), key=lambda x:x[1][0]/x[1][1]): print(f"  {n:14s} {g}/{t}")
print("\nFailures:")
for b,l in fails.items():
    print("==",b)
    for n,m,i,s in l: print(f"   {n:12s} -> {i}|{s}   {m[:90]!r}")
