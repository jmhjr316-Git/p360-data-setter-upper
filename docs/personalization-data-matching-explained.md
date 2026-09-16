# How Inbound-IVR Personalization Data Matching Works

*A plain-English explanation for the PC team of what has to line up for a caller to get a
personalized experience, and why "the patient exists" is not enough.*

---

## The one-sentence version

When a patient calls in, two completely separate systems have to independently agree on the
**same prescription for the same person** — the **P360 patient record** (who they are) and the
**pharmacy system / PMS** (what their prescription is doing right now). If those two disagree on
even one key field, the IVR falls back to the generic, non-personalized experience — **silently,
with no error**. It just quietly doesn't personalize.

That silent fallback is why this is so easy to get wrong and so confusing to debug.

---

## What actually happens on a call

```
Patient calls the pharmacy's number (DNIS)
        │
        ▼
1. channel-cfg-svcs   — "Which client/store owns this phone number?"
        │
        ▼
2. P360 (patient DB)  — "Do we know a patient at the CALLER'S phone number?"
        │                 → finds the patient record + their prescriptions
        ▼
3. pms-services       — "For that prescription, what's its LIVE status in the pharmacy system?"
        │                 → is it refillable? picked up? too soon? controlled?
        ▼
4. bot                — If everything lines up → personalized offer
                        ("Hi, calling about your Metformin refill?")
                        If anything is off      → generic menu, no personalization
```

The critical thing to understand: **step 2 and step 3 pull from two different data stores.**
P360 is the patient directory. The PMS (via pms-services and the simulator in QA) is the live
prescription state. Personalization only happens when the record from step 2 can be **matched**
to the live prescription from step 3.

---

## The matching contract — the fields that MUST agree

Think of it as a join between two records. For the IVR to treat them as "the same prescription
for the same caller," these have to match:

| # | What it is | P360 side (patient record) | PMS side (pharmacy/sim) | Why it matters |
|---|------------|----------------------------|--------------------------|----------------|
| 1 | **Caller's phone** | `phone.primary` | The number the patient is calling from (ANI) | This is how the patient is found at all. 10 digits, no country code. |
| 2 | **Prescription number** | `prescriptions[].rxNum` | The rx number pms-services returns | Ties the P360 record to a specific prescription. |
| 3 | **Last fill date** | `prescriptions[].fillDate` (YYYYMMDD) | `lastFillDate` | If these disagree, the systems think they're talking about different fills. |
| 4 | **Patient identity** | name + `dateOfBirth` | patient name + DOB on the rx | Confirms it's the same human. |

Plus a couple of "the record has to be usable at all" flags on the P360 side:

- `mdfcode` = `ACTIVE`
- `patientStatus` = `0`
- `clientId` / `storeId` have to be the client+store that owns the phone number (from step 1)

**If any of the matched fields (1–4) don't line up, or the patient record isn't ACTIVE, the call
falls back to generic. No error is logged that screams "mismatch" — it just doesn't personalize.**

---

## The other half: the prescription has to be in an offer-able STATE

Matching identifies the prescription. But personalization also depends on **what that
prescription is doing right now**, which pms-services computes from the live PMS data.

For a **refill reminder** to personalize, the prescription has to resolve to **REFILLABLE**. It
will NOT personalize a refill offer if the prescription is, for example:

- **Picked up too recently** (within ~5 days) → "RX_PICKED_UP", nothing to refill yet
- **Too soon** to refill (patient still has most of their supply) → "TOO_SOON"
- **Ready for pickup / in queue / waiting on prescriber** → it's mid-process, not refillable
- **A controlled substance** below the allowed schedule → blocked by policy

So "the patient exists and the rx matches" gets you halfway. The rx also has to be in a state
that the specific campaign is allowed to offer.

---

## Why "I created the patient, why doesn't it work?" happens

The most common failure we see: someone creates a P360 patient by hand, and it looks perfect —
right name, right phone. But its prescription's **fill date** or **rx number** was typed in
independently and doesn't match what the pharmacy system actually returns for that rx. Both
records exist; they just don't *join*. Result: generic experience, no error, hours of confusion.

That's exactly why our tooling always builds the **two records as a matched pair** from a single
source, so the four fields above are guaranteed to agree.

---

## Concrete working example (live in QA right now)

Phone **7249143802**, client **9001**, store **70050001** (PDX pharmacy), rx **7249001**:

**P360 record says:**
- phone.primary `7249143802`, name `TEST PERSONALIZATION`, DOB `19850101`, `mdfcode: ACTIVE`
- prescription: rxNum `7249001`, fillDate `20260817`, drug `METFORMIN 500MG TAB`

**pms-services returns for rx 7249001:**
- rxNum `7249001`, patient `TEST PERSONALIZATION`, DOB `19850101`, phone `7249143802`
- `lastFillDate: 20260817`, `rxStatus: OK`, `refillStatus: PICKED_UP` (picked up ~30 days ago)
- → resolves to **REFILLABLE**

Every matched field agrees, the patient is ACTIVE, and the rx resolves REFILLABLE — so a call
from 7249143802 gets the personalized refill experience.

*(Side note for the curious: on the PDX pharmacy path the drug NDC isn't returned by the pharmacy
system, so NDC isn't part of the match there. On some other pharmacy systems it is. The four
fields in the table above are the ones that always matter.)*

---

## TL;DR for PC

1. Personalization = a **join** between the P360 patient record and the live PMS prescription.
2. Four fields must agree: **caller phone, rx number, last fill date, patient identity (name+DOB).**
3. The patient record must be **ACTIVE** and owned by the **right client/store** for that phone.
4. The prescription must also be in an **offer-able state** (e.g. REFILLABLE for a refill reminder).
5. If any of that is off, the IVR **silently** falls back to generic — no error. So "the patient
   exists" is necessary but not sufficient; the two records have to actually *match*.
