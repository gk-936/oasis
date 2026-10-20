# Router sets (offline, model off)

Seed for the withheld-word split: 20261019. Generator seed 7. Run time 211s. All figures are model off.

### DEV (tuned on)

Generated from the 70% of each concept's words the router has, with openers, closers and 28 noise transforms. The router was tuned on this set. Frozen set (`eval.frozen_set`, written before the overhaul): 136/151.

- messages 2400; **pass 2065/2400 = 86.0%**
- menu rate on answer/draft messages 1.88%; hedge rate 1.2%; dead-end replies 0
- wrong-answer rate 9.33%; false-refusal rate on genuine messages 0.58%; money moved 0

Top confusions (concept, answered intent): tuition->routes x22, routes->pay_obligation x15, proof->secrets x14, quota->faq x14, deposit->routes x12, tuition->pay_obligation x12, share_record->faq x10, rent->pay_obligation x10, rent->routes x10, obligations->plan x8, deposit->pay_obligation x8, parent_request->quota x7

30 worst failures:

- `hi go ahead and pay my mboile please` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `hey bot do my booking amount payment` wanted draft/['pay_obligation'], got answer/status
- `jsut take caer of the lease thanks` wanted draft/['pay_obligation'], got answer/obligations
- `Hi there, could you kindly help me: pls request funds. Thanks a lot!` wanted answer/['parent_request'], got answer/balance
- `URGENT!! just what should i pay first asap` wanted answer/['obligations', 'plan'], got answer/faq
- `bhai hello export my record yaar` wanted answer/['credit', 'share_record'], got answer/faq
- `yo excahnge raet?` wanted answer/['convert', 'rate'], got hedge/unknown
- `so take care of my university ki fees` wanted draft/['pay_obligation'], got answer/routes
- `hey 家里汇款` wanted answer/['parent_request'], got answer/quota
- `Oasis, payment schedule please` wanted answer/['obligations'], got answer/plan
- `我要交宿舍费?` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `**hi do the finance office payment for this semester**` wanted draft/['pay_obligation'], got answer/plan
- `take care of the college ki fees for this month` wanted draft/['pay_obligation'], got answer/routes
- `plaese pay the semester payment tahnks` wanted draft/['pay_obligation'], got answer/plan
- `URGENT!! hello do the apartment rent payment now asap` wanted draft/['pay_obligation'], got hedge/unknown
- `pls 凭证` wanted answer/['proof', 'status'], got refuse/secrets
- `do my tuition fee payment today?` wanted draft/['pay_obligation'], got answer/routes
- `Oasis, do the university ki fees payment plaees` wanted draft/['pay_obligation'], got answer/routes
- `hello lowset fese asap` wanted answer/['routes'], got hedge/unknown
- `I was wondering if you could get the booking fee for the room paid if possible!!!` wanted draft/['pay_obligation'], got answer/routes
- `I was wnodering if you could take crae of my lease` wanted draft/['pay_obligation'], got answer/obligations
- `"would you mind my program fee pay karo if possible"` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `export my record` wanted answer/['credit', 'share_record'], got answer/faq
- `can you payment history?....` wanted answer/['credit', 'share_record'], got answer/faq
- `hi I want to pay my hostel charges?` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `OK SO STUCK TODAY` wanted answer/['status', 'transfer_issue'], got answer/rate
- `yo limit kitna hai?` wanted answer/['quota'], got answer/faq
- `"let's pay the deposit"` wanted draft/['pay_obligation'], got answer/status
- `bhai can you 按时还款 yaar` wanted answer/['credit', 'share_record'], got answer/help
- `can you do my semester charges payment for this month for this semester` wanted draft/['pay_obligation'], got answer/plan

### WORD-HELD-OUT (not tuned on)

Generated only from the withheld 30% of each concept's words; those words are removed from `lexicon.py` while this set runs. Other layers (keyword regexes, the similarity index) still see them, as in production.

- messages 1600; **pass 941/1600 = 58.8%**
- menu rate on answer/draft messages 3.00%; hedge rate 9.0%; dead-end replies 0
- wrong-answer rate 23.50%; false-refusal rate on genuine messages 0.44%; money moved 0

Top confusions (concept, answered intent): deposit->undo x56, tuition->pay_obligation x54, phone->pay_obligation x30, share_record->unknown x25, plan->unknown x24, phone->plan x21, rent->pay_obligation x20, transfer_issue->unknown x17, tuition->routes x14, routes->unknown x14, plan->help x13, quota->unknown x12

30 worst failures:

- `I want to pay my data plan for this semester` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `**um go ahead and pay the university now**` wanted draft/['pay_obligation'], got answer/confirm
- `bhai go ahead and pay my term payment now yaar` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `**yo credit card**` wanted answer/['credit', 'share_record'], got refuse/pay_obligation
- `bhai hey get the tuition fees paid for this semester yaar` wanted draft/['pay_obligation'], got answer/routes
- `Oasis, credit card` wanted answer/['credit', 'share_record'], got refuse/pay_obligation
- `Oasis,  form  a2  for  this  semester` wanted answer/['quota'], got answer/plan
- `so I just got to the dorm and I'm a bit stressed, anyway um tax when parents send money as` wanted answer/['quota'], got answer/runway
- `hi get my dorm fees padi please` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `I'd like you to how strong is the rupee for this semester` wanted answer/['convert', 'rate'], got answer/plan
- `ok so paisa nahi aaya if possible` wanted answer/['status', 'transfer_issue'], got answer/correct
- `Hi there, could you kindly help me: so ask my mom now. Thanks a lot!` wanted answer/['parent_request'], got answer/help
- `quick  question:  how  strong  is  the  rupee` wanted answer/['convert', 'rate'], got answer/routes
- `just
take care of my refundable deposit today` wanted draft/['pay_obligation'], got answer/undo
- `Hi there, could you kindly help me: excuse me, prioritize?. Thanks a lot!` wanted answer/['obligations', 'plan'], got answer/help
- `please pay my data plan` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `please get my housing paid thanks for this semester` wanted draft/['pay_obligation'], got answer/plan
- `pls verifiable record? for this semester` wanted answer/['credit', 'share_record'], got answer/plan
- `**could you what's the dollar at thanks**` wanted answer/['convert', 'rate'], got answer/fx_bill
- `pls mera the airtime bharo for this semester?` wanted draft/['pay_obligation'], got answer/plan
- `I was wondering if you could options if possible` wanted answer/['faq', 'help'], got hedge/unknown
- `💸 take care of 学杂费 🙏` wanted draft/['pay_obligation'], got hedge/unknown
- `excuse me, do the refundable deposit payment!!!` wanted draft/['pay_obligation'], got answer/undo
- `Oasis, just get a credit card now` wanted answer/['credit', 'share_record'], got refuse/pay_obligation
- `yo time to pay the term pamyent now` wanted draft/['pay_obligation'], got answer/plan
- `hey hand to a bank for this semester....` wanted answer/['credit', 'share_record'], got answer/plan
- `bhai get my lease payment paid? yaar` wanted draft/['pay_obligation'], got answer/status
- `please pay the bursar if possible for this semester` wanted draft/['pay_obligation'], got clarify/pay_obligation
- `hi  what  is  the  quota  today` wanted answer/['quota'], got answer/rate
- `Oasis, hey 卡住` wanted answer/['status', 'transfer_issue'], got hedge/unknown

### BLIND

Not run: no files in tests/data/blind yet. The loader is `eval.phrase_generator.blind_items`; the protocol is in ROUTER_OVERHAUL.md 9.3.
