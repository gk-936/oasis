# Regulatory and market sources for the INR -> CNY corridor

Research for the Oasis team. **Not legal advice and not certification.** It records what public pages said when read, so the team can confirm figures quickly with an authorised dealer (AD) bank or counsel. Retrieval date for everything below: **2026-10-11**. Rules change; re-check before any demo or release.

Method and limits: pages were fetched with a summarising web fetch tool, so "quotes" are short extracts as returned by that tool, not byte-exact copies. Several primary pages (incometaxindia.gov.in section page, Finance Bill 2026 PDF, Alipay help centre) returned HTTP 403 or a connection error and could not be read; where that happens the block says so and a labelled secondary source is used. Nothing here was verified against a printed gazette.

## Summary table

| Figure | Repo value (`oasis/trust/rules/inr_cny.yaml`) | Status | Confidence | Primary source |
|---|---|---|---|---|
| LRS annual limit | 250000 USD | MATCHES | High | RBI Master Direction on LRS (rbi.org.in, id=10192) |
| TCS education, self-funded | 2% above INR 10 lakh, nil below | MATCHES (secondary only for the 2026 rate) | Medium | Section 394, Income-tax Act 2025 (pre-amendment text read on mirror); Finance Act 2026 rate change per banks and tax portals. Official page 403 |
| TCS education loan (specified FI) | 0% | MATCHES | Medium | Section 394 exception text citing section 129(3)(b); bank and tax-portal charts |
| TCS other purposes (family, gifts, living, rent, deposit) | 2% PLACEHOLDER, unconfirmed | DIFFERS | Medium-high | Section 394(1) table item 7.D(b) / 7(b): 20% above INR 10 lakh (secondary sources, a bank notice agrees). Official page not readable |
| TCS threshold | INR 1,000,000 per remitter per FY | MATCHES | Medium-high | Section 394 table (same sources) |
| Purpose code, education | S0305 | UNCONFIRMED (consistent with secondary sources only) | Low-medium | RBI purpose-code annex not located in readable form |
| SAFE annual facilitation quota | 50000 USD per person per year | MATCHES (applies to settlement and purchase) | High for the figure; medium for how it applies to Oasis | SAFE Detailed Rules (safe.gov.cn), Article 2 |
| Wallet foreign-card fee | 3% over CNY 200 | MATCHES for WeChat Pay (official-ish); UNCONFIRMED for Alipay | Medium (WeChat), low (Alipay) | Beijing government English page, 2026-03-26 |
| Wallet caps | Not in yaml (README mentions reported caps) | UNCONFIRMED, sources conflict | Low | None official found |
| Hero university payment page | n/a | Example found: Shenzhen University | Medium (pages are 2022/2023) | lxs.szu.edu.cn |
| PIPL / DPDP / GDPR | n/a | Context only | Medium | See section 7 |
| Disclosure for robo-advice | n/a | Context only, hedged | Low-medium | See section 8 |

---

## 1. India LRS: USD 250,000 per financial year; education permitted

- **Repo:** `rules.lrs_annual_limit_usd.value: 250000`
- **Sources:**
  - RBI Master Direction on LRS: https://rbi.org.in/scripts/BS_ViewMasDirections.aspx?id=10192 (page showed "updated September 6, 2024" when read)
  - RBI FAQ: https://www.rbi.org.in/commonman/english/scripts/FAQs.aspx?Id=1834
- **Retrieved:** 2026-10-11
- **What they say:**
  - Master Direction: "Authorised Dealers may freely allow remittances by resident individuals up to USD 2,50,000 per Financial Year (April-March)."
  - FAQ: all resident individuals "including minors" may remit up to that amount; "Studies abroad" is a listed permitted purpose.
  - For studies, the Master Direction says an AD "may allow remittances (without seeking prior approval of the Reserve Bank of India) exceeding USD 2,50,000 based on the estimate received from the institution abroad." This is why education is not strictly capped at USD 250,000.
- **Match:** matches.
- **Confidence:** high. Primary source read directly.
- **Verify offline:** whether the bank counts earlier remittances the student's family made this FY under the same PAN; the limit is per individual remitter, so a parent remitting differs from a student remitting. Also confirm the Master Direction was not amended after the 2024-09 date shown (RBI page may be newer than the snippet read).

## 2. India TCS on LRS, FY 2026-27

- **Repo:** `tcs_threshold_inr.value: 1000000`, `rate_above: 0.02`, `loan_funded_rate: 0.0`; `tcs_by_purpose.education.rate: 0.02`, `education_loan.rate: 0.0`, `other.rate: 0.02` (placeholder, unconfirmed).
- **Legal framework (state of the law when read):**
  - Income-tax Act 2025 received assent 21 Aug 2025 and came into force 1 April 2026 (reported by Deccan Herald, newsonair.gov.in and Wikipedia; not read from a gazette). TCS on LRS moved from section 206C(1G) of the 1961 Act to **section 394(1) of the 2025 Act**, in the table at serial items 7.D(a) and 7.D(b) (as printed by tdsman.com), shown as "7(a)", "7(b)" in another chart. The loan exception sits in a sub-section that one chart labels 394(4)(b). Treat sub-section numbering as UNCONFIRMED; the section number 394 is consistent across sources. One bank page (Standard Chartered India) cites "section 506" for the same thing, which conflicts with every other source; ignore it unless a gazette copy says otherwise.
  - Finance Act 2026 reportedly received assent 30 March 2026 (taxmann.com headline). Budget 2026 cut the education and medical rate from 5% to 2% from 1 April 2026 and removed the threshold for overseas tour packages (2% flat).
- **Sources (labelled):**
  - PRIMARY, not readable: https://www.incometaxindia.gov.in/w/section-394-6 (HTTP 403); https://incometaxindia.gov.in/Budgets%20and%20Bills/2026/Finance_Bill-2026.pdf (HTTP 403).
  - SECONDARY, statute mirror (read): https://eztax.in/income-tax-act-2025/section-394 . It reproduces the pre-amendment table: LRS above ten lakh rupees, "5%" for "purposes of education or medical treatment", "20%" for "purposes other than education or medical treatment"; no collection "if the amount being remitted out is a loan obtained from any financial institution as defined in section 129(3)(b), for the purpose of pursuing any education". It does not show the Finance Act 2026 amendment (the page itself does not say it is amended).
  - SECONDARY, post-amendment charts (read): https://taxguru.in/income-tax/tcs-rate-chart-tax-year-2026-27-income-tax-act-2025.html (education or medical 2% above INR 10,00,000; other 20% above INR 10,00,000; loan from specified FI nil) and https://blog.tdsman.com/2026/09/tcs-on-foreign-remittances-and-overseas-tour-packages-section-3941-206c1g/ (same, with item numbers 7.D(a) and 7.D(b)).
  - SECONDARY, authorised-dealer bank notice (read): https://www.sc.bank.in/important-information/lrs-amendment-in-tcs/ . Effective 1 April 2026: education loan "Nil"; education, medical, travel "Nil up to 10 lakhs then 2% above"; other purposes "Nil up to 10 lakhs then 20% above (unchanged)". Its section cite (506) is the outlier noted above.
  - SECONDARY, news and payment providers (search snippets only): careers360, Outlook Money, Flywire.
  - Also 403: https://www.au.bank.in/faq/tax-on-collected .
- **Retrieved:** 2026-10-11
- **Education, self-funded:** nil up to INR 10 lakh per FY, 2% above. **Matches.** Medium confidence: three independent secondary sources and one bank agree; the only primary page that loaded predates the amendment.
- **Education loan from specified FI:** nil. **Matches.** The statute text says the financial institution is as defined in section 129(3)(b) of the 2025 Act (the old section 80E(8)(a) concept). Note the exemption covers the loan-funded part of the remittance only.
- **Other purposes (family maintenance, gifts, living expenses, rent, deposits):** **DIFFERS from the repo placeholder.** Every source read says **20% on the amount above INR 10 lakh** (nil below, threshold shared across purposes per remitter per FY), unchanged by Budget 2026. The yaml's 2% is wrong for these purposes. Confidence medium-high: consistent across the statute mirror's non-education row, two tax portals and a bank notice, but not confirmed on an official page.
- **Budget 2026 changes:** education and medical 5% to 2%; overseas tour packages a flat 2% with no threshold; other-purpose 20% unchanged. The threshold stayed at INR 10 lakh (raised from 7 lakh in Budget 2025).
- **Verify offline:**
  - Get the AD bank to state the rate it will actually collect per purpose code, and whether the INR 10 lakh threshold is tracked across all purposes and across all banks the remitter uses (the threshold is aggregate per PAN, but banks may only see their own transactions).
  - Whether the remitter is the student or a parent changes whose PAN and FY threshold apply.
  - How a mixed remittance (tuition plus living costs) is split and coded.
  - The higher rate for no PAN or no Aadhaar linkage (secondary sources mention it; not verified here).
  - Counsel: sub-section numbering of the loan exception and whether any CBDT notification changed the rates after 1 April 2026.

## 3. RBI purpose codes

- **Repo:** `purpose_code_education.value: S0305`, status unconfirmed.
- **Primary source attempt:** RBI Master Direction on Reporting under FEMA (https://rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=10202; shown as updated 1 October 2026 when read). The visible page did not contain the purpose-code list; the list is in a linked PDF that was not opened. The LRS Master Direction page also lists purposes by category without codes.
- **Secondary sources (read or in search results):**
  - Skydo, https://www.skydo.com/rbi-purpose-codes/S0305-paying-for-overseas-education-travel : S0305 = "Travel for education (including fees, hostel expenses etc.)". The page does not cite an RBI document.
  - Search snippets from BookMyForex, Razorpay and Xflow list: S0305 education travel including fees and hostel; S1301 family maintenance and savings; S1302 personal gifts and donations; S0306 other travel; S1303 donations to religious and charitable institutions; S1107 education-related services such as correspondence courses; S1108 health services. These were not individually opened.
- **Match:** S0305 is consistent with every secondary source, so no change is recommended, but it stays UNCONFIRMED. Confidence low-medium.
- **Verify offline:** ask the AD bank which code its form (A2 or its online equivalent) requires for tuition paid directly to a Chinese university and for hostel or living costs, and for family support (likely S1301). Some banks use their own code picker. One search snippet wrongly pairs the codes with the old 5% TCS rate, a reminder that those pages are not reliable on tax.

## 4. China SAFE: individual facilitation quota

- **Repo:** `safe_quota_usd.value: 50000`, action `plan_staged_conversion`, source "SAFE circular + HSBC China individual FX guide".
- **Sources:**
  - SAFE English, Detailed Rules for Implementing the Measures for the Administration of Individual Foreign Exchange (issued 2007-01-05): https://www.safe.gov.cn/en/2007/0105/819.html . Says the annual purchase quota was "drastically raised from USD 20,000 to USD 50,000" with a matching quota for settlement, for domestic and foreign individuals. This is an old text; the current Chinese version is better.
  - SAFE Tianjin branch, Chinese text of the Detailed Rules (read): https://www.safe.gov.cn/tianjin/2024/0430/2464.html . Article 2: "年度总额分别为每人每年等值5万美元" (annual totals of USD 50,000 equivalent per person per year, for settlement and for domestic individuals' purchase). Article 11 covers foreign individuals' (境外个人) settlement above quota, with supporting documents including "就医、学习等支出：境内医院（学校）收费证明" (school fee proof for education expenses), and says settlements of USD 50,000 or more in a single transaction must be transferred directly to the counterparty's domestic RMB account. The page is headed "（已修改）", i.e. amended.
  - SAFE Tianjin Q&A 2025-07-14 and 2025-12-23: https://www.safe.gov.cn/tianjin/2025/0714/2833.html and https://www.safe.gov.cn/tianjin/2025/1223/2957.html . An individual may choose whether a purchase uses the quota (valid ID only) or does not (ID plus documents such as an admission notice). Quoted rule: "Domestic individuals enjoy annual convenience quotas of equivalent USD 50,000 for both settlement and foreign exchange purchase", citing the Current Account FX Business Guidelines (2020 edition), 汇发〔2020〕14.
- **Retrieved:** 2026-10-11
- **Match:** the USD 50,000 per person per year figure matches. The repo says "for foreigners"; the sources read apply the figure to settlement and purchase generally, with foreigners' over-quota settlement handled through documents (Article 11). A search snippet says the quota for foreigners applies "to foreign exchange settlement only" and resets on 1 January; that came from a non-official page and is not confirmed.
- **What counts / documents above the quota:** non-business current-account settlement; over-quota needs authenticity documents (for foreigners: lease, consumption contract or invoice, domestic school or hospital fee proof). For study, school fee proof or admission notice is the named document.
- **Relevance caveat for Oasis:** the quota governs a person in China converting foreign currency into RMB or buying foreign currency. A payment from India that lands directly in a university's account may never touch the student's personal quota. It matters mainly when family funds arrive as foreign currency in a student's China account and the student converts to RMB for living costs. The team should decide which flow the product models. Confidence high on the figure, medium on applicability.
- **Verify offline:** with the receiving Chinese bank (and the university's finance office), whether INR is accepted or converted to USD first, per-bank handling of foreign students' settlement, and whether the bank counts the quota per calendar year per person across banks (reported, not confirmed).

## 5. Alipay and WeChat Pay foreign-card fees and limits

- **Repo:** `wallet_foreign_card_fee: rate 0.03, applies_over_cny 200`, source "Alipay in-app customer service per May 2026 report; check in app".
- **Sources:**
  - Beijing municipal government English site, 2026-03-26 (read): https://english.beijing.gov.cn/travellinginbeijing/essentials/inboundtourismfacilitationmeasures/202603/t20260326_4566766.html . Quote: "All international bank card users are eligible for a waiver of the 3 percent transaction fee on every single transaction under 200 yuan." This is about WeChat Pay per the page title in search results. It implies a 3% fee above 200 yuan but does not state that outright.
  - Shanghai education commission, 2023-08-08 (read): https://edu.sh.gov.cn/study_en_living/20240129/e217cc4de8244143bb42776d8bc2ef7f.html . Fee exemption under 200 yuan; no limits stated.
  - Alipay official help (cschannel.alipay.com help_id=201602777221): **could not be fetched** (connection refused). Alipay global docs and "Tour Pass" pages appear in search but concern other products (the Tour Pass prepaid card shows a 5% fee, which is not the in-app foreign-card payment). No official Alipay wording on 3% over 200 was read.
  - Secondary guides (labelled): travelofchina.com (updated 2026-06-26) says USD 5,000 per transaction and USD 50,000 per year after passport verification, 3% above 200 yuan, and cites no official source. A search summary quotes WeChat's own help page as still publishing RMB figures (about CNY 6,000 per transaction, 50,000 per month, 60,000 per year in one version; 6,500 and 65,000 in another). These disagree with each other and were not verified.
- **Retrieved:** 2026-10-11
- **Match:** 3% over CNY 200 matches the official-ish WeChat Pay wording (the waiver under 200 implies it). Alipay's own wording is UNCONFIRMED. Caps: UNCONFIRMED, with three conflicting sets reported. Do not state any cap as fact in the UI.
- **Confidence:** medium for the fee on WeChat Pay, low for Alipay, low for caps.
- **Relevance:** these fees apply to foreign-issued cards used in the wallets, not to an INR bank transfer. Say so wherever the fee is shown.
- **Verify offline:** open the in-app help in Alipay and WeChat on a phone with a foreign card linked and screenshot the fee and limit text; note the app version and date.

## 6. How Chinese universities receive international tuition; example page

- Typical pattern (from the Shenzhen University pages below and a search hit for Peking University): published bank account for the university, payment in RMB or USD equivalent, passport number in the remark, then an email to the international office with a receipt screenshot. Alipay or WeChat QR codes are offered by some universities on request.
- **Example with public English instructions (Shenzhen University, Office of International Students, "境外学历生缴费指引"):**
  - 2022 spring: https://lxs.szu.edu.cn/info/1003/2522.htm (dated 2022-02-13)
  - 2023 spring: https://lxs.szu.edu.cn/info/1003/2849.htm (dated 2023-02-07)
  - What they say: account name SHENZHEN UNIVERSITY at Bank of China Shenzhen Branch Shenda Sub-branch, SWIFT BKCHCNBJ45A; pay "RMB or in the equivalent amount of U.S. dollars"; remark "student passport number + tuition"; email cieoffice@szu.edu.cn with the student name, payer name, payer passport image and receipt screenshot; transfers "non-refundable"; Alipay and WeChat QR codes available via that email and marked "Recommended". The account number shown on the pages is public but is deliberately not copied here, because it must be re-read from the current page before any real use.
  - Caveats: both pages are older (2022, 2023) and tied to specific semesters, so the account and process may have changed. A newer page was not found. A third-party search summary shows the same account, which suggests it is stable, but that is not verification.
- SUSTech, CUHK-Shenzhen and SZTU: searches did not return a public English tuition payment page. **UNCONFIRMED**; I did not find one, which is not proof none exists.
- **Suggestion for the hero choice:** Shenzhen University is the only one with a findable page, and it matches the "bank transfer plus WeChat/Alipay option" story. The team should ask the university's international office for the current-year instructions in writing before the demo.
- **Retrieved:** 2026-10-11.

## 7. Data protection frameworks (design alignment, not compliance)

All of this is a high-level pointer. None of it is a compliance assessment.

**China PIPL (effective 1 Nov 2021).**
- Sources: Article 28 text via https://prighter.com/resources/laws/chinese-pipl/articles/article-28 (search result; not opened); Article 38/39 via law firm summaries (CMS, Paul Weiss, Morgan Lewis in search results; not opened). Primary gov.cn text not read.
- Article 28 lists "financial accounts" among sensitive personal information, processable only with a specific purpose, sufficient necessity and strict protection (Article 29 adds separate consent, not verified here). Article 38 gives three routes for sending personal information out of China (security assessment, certification, standard contract); Article 39 requires notice and separate consent for the transfer. Newer rules (2024 exemptions for small volumes) exist but were not checked; UNCONFIRMED.
- Applies to Oasis if it processes personal information of individuals in China, or of people in China (for example the payee, a Chinese landlord, or a student located in China), and where data moves back to India.
- Design alignment: data minimisation, screenshots discarded after extraction, encryption at rest and the audit log all support the "necessity", "protective measures" and accountability themes. Not covered by design alone: explicit separate consent flows, a cross-border mechanism, and local representative or officer duties, which need counsel.

**India DPDP Act 2023 and Rules 2025.**
- Sources: https://www.scconline.com/blog/post/2025/12/26/digital-personal-data-protection-rules-2025-key-highlights/ (read), plus JSA, S.S. Rana and Mondaq results (search only); MeitY gazette not read.
- Status as read: Rules notified 13/14 November 2025; board and administrative rules in force at once; consent manager rules after 12 months (13 Nov 2026); core duties (notice, consent, security safeguards, breach intimation, retention and deletion, data principal rights) after 18 months (13 May 2027). In Jan-Feb 2026 MeitY consulted on cutting the 18 months to 12 months (to 13 Nov 2026). Whether that was finalised is **UNCONFIRMED**; check the current MeitY gazette.
- Obligations that would apply to Oasis as a data fiduciary for Indian users: notice and consent, purpose limitation, reasonable security (the Rules mention encryption, access controls, audit logging), breach notification, deletion when the purpose ends, and logs kept for a minimum period (the summary read says at least one year).
- Design alignment: matches in spirit on minimisation, encryption at rest and the audit log. The audit log retention period, user deletion and breach flows are the likely gaps to check.

**GDPR (only if EU students are users).**
- No source read for this task; general knowledge only and UNCONFIRMED. If EU residents' data is processed, GDPR applies by territorial scope: lawful basis, transparency, data subject rights, security, breach notice within 72 hours, and transfer rules for sending data to India or China. Design alignment is similar to the above; a representative and transfer mechanism would need counsel.

## 8. Disclosure for digital financial assistance (hedged)

- **India:** investment advice by automated tools falls under the SEBI (Investment Advisers) Regulations, 2013 as understood from a Mondaq explainer (search summary), including disclosure of how a tool works. RBI digital-lending directions require standardised disclosures such as a Key Fact Statement for loans. Oasis does not give investment advice or lend, so neither clearly applies; no rule was found that mandates a specific "not licensed advice" disclaimer for a payments assistant. Sources are search summaries only; no regulator page was read.
- **China:** a news report (asianprivatebanker.com, undated in the summary) says PBOC asked institutions using AI for investment advisory to disclose algorithm assumptions and asset-allocation methods. This concerns licensed institutions. Not verified on pbc.gov.cn.
- **Conclusion:** the disclosure is prudent product practice and consistent with the direction of regulators in both countries, but this research did not find a rule that obliges Oasis specifically. Ask counsel whether any activity (comparing rates, recommending when to convert, execution on the user's behalf) pulls Oasis into a licensed category (payment aggregator, advisory, FX intermediary).

---

## Discrepancies to fix in the repo

File: `oasis/trust/rules/inr_cny.yaml`

1. `tcs_by_purpose.other.rate`: change from `0.02` to `0.20` (20% on the amount above INR 10 lakh per FY). Update the comment block and the `source` (cite section 394(1) table item 7.D(b), Income-tax Act 2025, as amended by Finance Act 2026), and keep `status: unconfirmed` until an official page or the AD bank confirms it, or set `status: researched` with the source labelled secondary. The current placeholder understates TCS on non-education purposes by a factor of ten and flows into user-facing arithmetic via `purpose_tcs_category` (`rent`, `deposit`, `living`, `family_support`).
2. `tcs_threshold_inr.source` and `tcs_by_purpose.education.source`: replace "Finance Act 2026 changes (Flywire etc.)" with "section 394(1), Income-tax Act 2025 (formerly 206C(1G), Income-tax Act 1961), as amended by Finance Act 2026; bank notice sc.bank.in; taxguru chart", and note that the incometaxindia.gov.in page was not readable.
3. `tcs_by_purpose.education_loan.source`: add "section 129(3)(b) financial institution (formerly 80E)" and the loan-funded-part-only caveat.
4. `purpose_code_education`: value S0305 can stay; keep `status: unconfirmed`. Add the description "Travel for education (including fees, hostel expenses etc.)" and note the RBI annex was not read.
5. `safe_quota_usd.source`: replace "SAFE circular + HSBC China individual FX guide" with "SAFE Detailed Rules for Implementing the Measures for the Administration of Individual Foreign Exchange, Article 2 (safe.gov.cn/tianjin/2024/0430/2464.html); 汇发〔2020〕14". Reword so it says the quota applies to settlement and purchase per person per calendar year, and that foreign individuals above the quota use Article 11 documents such as school fee proof.
6. `wallet_foreign_card_fee.source`: replace "Alipay in-app customer service per May 2026 report" with the Beijing government page for WeChat Pay and mark Alipay as unconfirmed. Add a note that the fee is for foreign cards in the wallets, not for INR bank transfers.
7. `lrs_annual_limit_usd`: value is right. Change `status` to `official` (primary RBI page read) and the source to the RBI Master Direction URL; add that studies abroad can exceed USD 250,000 with an institution estimate.
8. README "Known limitations" item 12: it can say the non-education TCS rate is now believed to be 20% (secondary sources), instead of just "a marked placeholder".
9. Anywhere the UI or docs state wallet caps (README "reported per-transaction/annual caps"): label them unconfirmed; the sources conflict.

## Questions only an authorised dealer bank / counsel can answer

For the AD bank:
- What TCS will you collect, by purpose code, for FY 2026-27 (education self-funded, education loan, family maintenance, gifts, rent, deposits)? Please state the rate in writing.
- How do you track the INR 10 lakh threshold across banks and across the student's and parents' PANs?
- Which purpose code and which form do you require for tuition paid to a named Chinese university, for hostel fees, and for living costs sent to the student?
- Does a loan from a specified financial institution under section 129(3)(b) need a certificate or loan sanction letter at the time of remittance, and does the nil rate cover only the loan-funded portion?
- Is INR to CNY direct possible, or does the bank convert via USD? What are the rate, spread and fees, and what do you need from the university (invoice, admission letter)?
- Will you remit to a university's published account on instructions from a third-party app, or only from the customer's own channel?

For the Chinese side (university finance office or receiving bank):
- Which accounts and currencies are accepted this academic year; is the published Shenzhen University instruction page current?
- Does a student's own quota get used when family funds arrive in foreign currency and are converted, and what documents are needed above USD 50,000?

For counsel:
- Whether Oasis's role (instructing remittances, comparing options, drafting payments for approval) needs any licence in India (RBI, SEBI) or China, and whether any activity counts as financial advice or payment services.
- PIPL and DPDP obligations for the actual data flows (India to China and back), consent wording, and the status of the DPDP timeline in November 2026 and May 2027.
- Whether the "not licensed financial advice" disclosure is sufficient or required, and in what wording.
- Section 394 sub-section numbering and any CBDT circulars after 1 April 2026.

*Prepared 2026-10-11 as team research. Not legal advice, not certification, not a compliance opinion.*
