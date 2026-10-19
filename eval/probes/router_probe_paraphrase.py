import os, sys, collections
os.environ.update({"OASIS_DB": ":memory:", "OASIS_LLM": "offline", "OASIS_EXTRACT": "deterministic", "OASIS_LLM_RISK": "0",
 "OASIS_CHAT_LLM": "0", "OASIS_ML_RISK": "0", "OASIS_ANCHOR": "local", "OASIS_PASS_STUDENT": "student-demo",
 "OASIS_PASS_PARENT": "parent-demo", "OASIS_PASS_JUDGE": "judge-demo", "OASIS_RATES": "mock"})
sys.path.insert(0, sys.argv[1])
from tests.auth_helpers import new_client
st = new_client("student")
def ask(m):
    st.post("/api/reset"); j = st.post("/api/chat", json={"message": m}).json(); return j
P = {
"STATEMENT/INDIRECT": [
 ("my tuition is due on Friday", {"obligations","pay_obligation"}),
 ("I'm worried I won't have enough for rent next month", {"runway","plan","finance_summary"}),
 ("I think I owe the university some money", {"obligations","pay_obligation"}),
 ("the landlord is chasing me", {"obligations","pay_obligation"}),
 ("I forgot to pay my phone bill", {"pay_obligation"}),
 ("my dad said he sent the money but I don't see it", {"transfer_issue","where","status"}),
 ("rupee has fallen again, bad time to convert?", {"rate","convert","rate_target","routes","explain"}),
 ("I need a bank reference letter and have no credit history", {"credit","share_record"}),
 ("fees deadline is tomorrow!!", {"obligations","pay_obligation"}),
 ("bills are piling up", {"obligations","finance_summary"}),
],
"PARAPHRASE_PAY": [
 ("clear my dues with the university", {"pay_obligation"}),
 ("take care of the hostel charges", {"pay_obligation"}),
 ("I'd like to settle up with my landlord", {"pay_obligation"}),
 ("send the semester payment to the school", {"pay_obligation"}),
 ("get my accommodation paid", {"pay_obligation"}),
 ("remit this month's flat rent", {"pay_obligation"}),
 ("top up my phone", {"pay_obligation"}),
 ("pay the college", {"pay_obligation"}),
 ("do the tuition payment", {"pay_obligation"}),
 ("proceed with paying the lease", {"pay_obligation"}),
],
"PARAPHRASE_INFO": [
 ("what am I supposed to pay this month", {"obligations"}),
 ("list everything I need to pay", {"obligations"}),
 ("anything due soon?", {"obligations"}),
 ("how much cash do I have", {"balance"}),
 ("what's in my account", {"balance"}),
 ("show my wallets", {"balance"}),
 ("how many dollars do I have", {"balance"}),
 ("what's today's yuan rate against the rupee", {"rate"}),
 ("how strong is the rupee vs the yuan right now", {"rate"}),
 ("rupee to RMB?", {"rate","convert"}),
 ("how far will my money last", {"runway"}),
 ("when will I run out of money", {"runway"}),
 ("will my savings cover the next 3 months", {"runway","plan"}),
 ("what did I spend on last month", {"spending"}),
 ("where does my money go", {"spending","finance_summary"}),
],
"PARAPHRASE_REMIT": [
 ("what's the least expensive method to move 50000 rupees to China", {"routes"}),
 ("should I use a bank or Wise or Western Union", {"routes","markup_check"}),
 ("which service has the lowest fees for international transfers", {"routes"}),
 ("how quickly will an international transfer get there", {"routes","transfer_time"}),
 ("is there a limit on how much my family can send abroad", {"quota"}),
 ("LRS limit?", {"quota"}),
 ("do I pay tax when my parents send me money", {"quota","faq","explain"}),
 ("TCS on education remittance", {"quota","faq","explain"}),
 ("my transfer is stuck", {"transfer_issue"}),
 ("it's been a week and the university says they haven't got my payment", {"transfer_issue","where"}),
 ("money went missing in transit", {"transfer_issue"}),
 ("can my mother pay in rupees and the school receive yuan", {"routes","parent_request","convert"}),
 ("ask my father to send 2 lakh", {"parent_request"}),
 ("request money from my parents", {"parent_request"}),
],
"PARAPHRASE_CREDIT": [
 ("how can I establish a credit score in China", {"credit"}),
 ("I want a financial reputation here", {"credit"}),
 ("can this app help me get a credit card", {"credit"}),
 ("prove to my landlord I'm trustworthy", {"share_record","credit"}),
 ("export my payment record", {"share_record","proof"}),
 ("what's a trust pass", {"credit","share_record","faq","glossary","help"}),
 ("have my payments been reported anywhere", {"credit","faq"}),
 ("am I building credit by using this", {"credit"}),
],
"PARAPHRASE_FX": [
 ("swap 5000 yuan for rupees", {"convert"}),
 ("change my dollars to yuan", {"convert"}),
 ("I want to exchange 100 GBP", {"convert"}),
 ("exchange everything into yuan", {"convert"}),
 ("buy USD with 30000 INR", {"convert"}),
 ("what would 1000 AUD be in rupees", {"convert","rate"}),
 ("notify me if the dollar hits 85 rupees", {"rate_target"}),
 ("wait until the rate is better then convert 10000", {"rate_target"}),
 ("I owe 50 pounds to a British lab", {"fx_bill"}),
 ("pay a 30 SGD charge", {"fx_bill"}),
 ("pay my Canadian dollar fee", {"fx_bill"}),
],
"SAFETY_NET/CONTROL": [
 ("stop, wrong amount", {"cancel","correct"}),
 ("wait, change it to 2500", {"correct"}),
 ("undo that", {"undo","cancel"}),
 ("no, not that one", {"deny","cancel","correct"}),
 ("how do I know this isn't a scam", {"scam_check","explain","faq","help"}),
 ("is it safe to give you my bank details", {"secrets","explain","faq","help"}),
 ("what happens if I get hacked", {"explain","faq","help"}),
 ("what can go wrong with a payment", {"explain","faq","transfer_issue"}),
 ("can you reverse a payment", {"undo","explain","faq","transfer_issue"}),
 ("show me proof it was paid", {"proof","status"}),
],
"MULTI/CONTEXT": [
 ("pay rent and tuition", None),
 ("pay my rent then check my balance", None),
 ("how much is the rent and can I afford it", None),
 ("convert 5000 yuan and tell me the rate", None),
 ("what about the other one", None),
 ("same again", None),
 ("and my phone?", None),
 ("ok do it", None),
],
}
tot=ok=dead=0; cat=collections.defaultdict(lambda:[0,0]); rows=[]
for c,l in P.items():
    for m,exp in l:
        j=ask(m); i=j.get("intent"); s=j.get("status"); r=j.get("reply") or ""
        if exp is None: rows.append((c,"----",m,i,s,r)); continue
        good = i in exp; tot+=1; ok+=good; cat[c][0]+=good; cat[c][1]+=1
        rows.append((c,"PASS" if good else ("DEAD" if i in ("unknown","clarify") or s=="unknown" else "WRONG"),m,i,s,r))
print(f"PARAPHRASE {ok}/{tot} = {100*ok/tot:.0f}%")
for c,(g,t) in cat.items(): print(f"  {c:22s}{g}/{t}")
print()
for c,v,m,i,s,r in rows:
    if v!="PASS": print(f"{v:5s} [{i}|{s}] {m!r}\n        -> {r[:140]!r}")
