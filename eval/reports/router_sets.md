# Router sets (offline, model off)

Seed for the withheld-word split: 20261019. Generator seed 7. Run time 638s. All figures are model off.

### DEV (tuned on)

Generated from the 70% of each concept's words the router has, with openers, closers and 28 noise transforms. The router was tuned on this set. Frozen set (`eval.frozen_set`, written before the overhaul): 136/151.

- messages 2400; **pass 2085/2400 = 86.9%**
- menu rate on answer/draft messages 1.50%; hedge rate 1.1%; dead-end replies 0
- wrong-answer rate 9.29%; false-refusal rate on genuine messages 0.29%; money moved 0

Top confusions (concept, answered intent): tuition->routes x18, quota->faq x15, rent->pay_obligation x11, parent_request->faq x10, deposit->pay_obligation x10, rent->routes x10, tuition->pay_obligation x10, parent_request->quota x9, obligations->plan x9, share_record->faq x9, rent->help x9, deposit->routes x9

30 worst failures:

- `hi go ahead and pay my mboile please` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `Oasis,  先付哪个` wanted answer/['obligations', 'plan'], got answer/help
- `so I just got to the dorm and I'm a bit stressed, anyway I was wondering if you could 家里汇款` wanted answer/['parent_request'], got draft/pay_obligation
- `bhai um 先付哪个 yaar` wanted answer/['obligations', 'plan'], got answer/quota
- `jsut take caer of the lease thanks` wanted draft/['pay_obligation'], got answer/obligations
- `message my parents thanks....` wanted answer/['parent_request'], got answer/faq
- `hey 家里汇款` wanted answer/['parent_request'], got answer/quota
- `bhai request funds for this semester yaar` wanted answer/['parent_request'], got answer/balance
- `ok so paisa nahi aaya now....` wanted answer/['status', 'transfer_issue'], got answer/correct
- `Oasis, payment schedule please` wanted answer/['obligations'], got answer/plan
- `我要交宿舍费?` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `**hi do the finance office payment for this semester**` wanted draft/['pay_obligation'], got answer/plan
- `take care of the college ki fees for this month` wanted draft/['pay_obligation'], got answer/routes
- `plaese pay the semester payment tahnks` wanted draft/['pay_obligation'], got answer/plan
- `URGENT!! hello do the apartment rent payment now asap` wanted draft/['pay_obligation'], got hedge/unknown
- `so I just got to the dorm and I'm a bit stressed, anyway I'd like you to available funds n` wanted answer/['balance'], got answer/runway
- `financial reefrnece asap` wanted answer/['credit', 'share_record'], got hedge/unknown
- `I was wondering if u could settle my deposit?` wanted draft/['pay_obligation'], got answer/status
- `SO 家里汇款` wanted answer/['parent_request'], got answer/quota
- `so I want to pay the booking amount?` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `um ask my parents for this month` wanted answer/['parent_request'], got answer/faq
- `HEY EDUCATION REMITTANCE TAX` wanted answer/['quota'], got answer/faq
- `hi I want to pay my hostel charges?` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `hey bot pay the phoen now` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `education remittance tax thanks` wanted answer/['quota'], got answer/faq
- `yo limit kitna hai?` wanted answer/['quota'], got answer/faq
- `"let's pay the deposit"` wanted draft/['pay_obligation'], got answer/status
- `hey  bot  prioritise  if  possible` wanted answer/['obligations', 'plan'], got answer/help
- `bhai can you 按时还款 yaar` wanted answer/['credit', 'share_record'], got answer/help
- `can you do my semester charges payment for this month for this semester` wanted draft/['pay_obligation'], got answer/plan

### WORD-HELD-OUT (not tuned on)

Generated only from the withheld 30% of each concept's words; those words are removed from `lexicon.py` while this set runs. Other layers (keyword regexes, the similarity index) still see them, as in production.

- messages 1600; **pass 943/1600 = 58.9%**
- menu rate on answer/draft messages 4.00%; hedge rate 9.7%; dead-end replies 0
- wrong-answer rate 21.25%; false-refusal rate on genuine messages 0.69%; money moved 0

Top confusions (concept, answered intent): tuition->pay_obligation x63, deposit->undo x52, phone->pay_obligation x33, rent->pay_obligation x26, plan->unknown x25, transfer_issue->unknown x20, phone->plan x18, routes->unknown x16, tuition->routes x14, spending->unknown x14, share_record->unknown x14, share_record->proof x14

30 worst failures:

- `I want to pay my data plan for this semester` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `**um go ahead and pay the university now**` wanted draft/['pay_obligation'], got answer/confirm
- `can you audit trail please!!!` wanted answer/['proof', 'status'], got answer/faq
- `bhai go ahead and pay my term payment now yaar` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `**yo credit card**` wanted answer/['credit', 'share_record'], got refuse/pay_obligation
- `bhai hey get the tuition fees paid for this semester yaar` wanted draft/['pay_obligation'], got answer/routes
- `Oasis, credit card` wanted answer/['credit', 'share_record'], got refuse/pay_obligation
- `💸 um kharcha 🙏` wanted answer/['spending'], got hedge/unknown
- `Oasis,  form  a2  for  this  semester` wanted answer/['quota'], got answer/plan
- `so I just got to the dorm and I'm a bit stressed, anyway um tax when parents send money as` wanted answer/['quota'], got answer/runway
- `hi get my dorm fees padi please` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `ok so i can't see it if possible` wanted answer/['status', 'transfer_issue'], got hedge/unknown
- `Hi there, could you kindly help me: so ask my mom now. Thanks a lot!` wanted answer/['parent_request'], got answer/help
- `hey I have to pay my airtime` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `Hi there, could you kindly help me: excuse me, how should i split?. Thanks a lot!` wanted answer/['obligations', 'plan'], got answer/help
- `please pay my data plan` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `please get my housing paid thanks for this semester` wanted draft/['pay_obligation'], got answer/plan
- `hey bot lowets charges today` wanted answer/['routes'], got hedge/unknown
- `QUICK QUESTION: FORM A2 NOW` wanted answer/['quota'], got hedge/unknown
- `excuse me, yuan to ruepe please` wanted answer/['convert', 'rate'], got clarify/convert
- `could you clear the academic fees thanks!!!` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `I was wondering if you could options if possible` wanted answer/['faq', 'help'], got hedge/unknown
- `💸 take care of 学杂费 🙏` wanted draft/['pay_obligation'], got hedge/unknown
- `excuse me, do the refundable deposit payment!!!` wanted draft/['pay_obligation'], got answer/undo
- `I was wondering if you could hand to a bank if possible` wanted answer/['credit', 'share_record'], got hedge/unknown
- `Oasis, just get a credit card now` wanted answer/['credit', 'share_record'], got refuse/pay_obligation
- `yo time to pay the term pamyent now` wanted draft/['pay_obligation'], got answer/plan
- `hello verifiable record for this semester` wanted answer/['credit', 'share_record'], got answer/plan
- `I WAS WONDERING IF YOU COULD GENERATE SOMETHING I CAN HAND THANKS` wanted answer/['credit', 'share_record'], got hedge/unknown
- `"hey bot settle my lease payment if possible"` wanted draft/['pay_obligation'], got answer/help

### BLIND

Not run: no files in tests/data/blind yet. The loader is `eval.phrase_generator.blind_items`; the protocol is in ROUTER_OVERHAUL.md 9.3.
