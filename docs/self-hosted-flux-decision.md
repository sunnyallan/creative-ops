# Should Creative Ops self-host Flux + train per-tenant LoRAs?

**Decision date:** _____ • **Decided by:** _____ • **Revisit:** in 6 weeks

---

## TL;DR

Today's stack (Gemini Nano Banana Pro) is the right call for a beta with <10 tenants. Self-hosted Flux + LoRAs becomes the right call once **one of three triggers fires**:

1. Cost — sustained >2,000 images/month across all tenants
2. Quality — a real prospect says "I'll pay if creatives look like *our* brand"
3. Compliance — a customer with data-residency requirements

Don't build it speculatively. Validate the trigger first, then commit ~5 weeks of work.

---

## The two architectures, side by side

|  | Gemini today | Self-hosted Flux + per-tenant LoRAs |
|---|---|---|
| **Image model** | `gemini-3-pro-image` | `flux.1-schnell` (or `dev` for higher quality) |
| **Inference location** | Google US | Your GPU (Modal / Replicate / RunPod / own metal) |
| **Cost per image** | ~$0.15 flat | $0.005–0.02 amortised on dedicated GPU |
| **Latency** | 5–10s | 2–4s (Schnell is 4-step) |
| **Brand consistency** | Generic | Locked once LoRA trains on ~30 approved samples |
| **Cold-start quality** | Excellent | Lower until LoRA learns brand |
| **Vendor lock-in** | High | None (weights are Apache 2.0) |
| **Setup effort** | Zero | ~30 hours |
| **Ongoing maintenance** | Zero | ~5 hours/month |
| **Defensibility / moat** | None | Real (each tenant has unique trained model) |

---

## Cost crossover

Per-image cost assumed:

- Gemini Pro Image: $0.15
- Flux Schnell on Modal (serverless): ~$0.005 + $50/mo idle reservation
- Flux Schnell on RunPod A10G dedicated: ~$0.79/hr × 730 = $577/mo

Break-even points:

| Volume / month | Cheapest option |
|---|---|
| 0 – 350 images | **Gemini** ($0–50) |
| 350 – 1,500 images | **Modal serverless** Flux |
| 1,500+ images | **Dedicated GPU** Flux |
| 5,000+ images | **Multiple dedicated GPUs** Flux |

You're currently at ~50 images/month across beta. Cost trigger is **30x away**.

---

## Effort to build

Phased, not all-or-nothing:

| Phase | Scope | Engineer hours |
|---|---|---|
| **1** | Self-host Flux Schnell, swap `_gen_image()` to call it | 30–40 |
| **2** | LoRA training pipeline + storage + hot-swap at inference | 60–80 |
| **3** | Feedback-weighted retraining, reference image uploads, scheduled jobs | 40–60 |
| **4** | Auto-scaling, batching, hot LoRA cache, Gemini fallback | 30–40 |

Phase 1 alone is a science experiment — not customer value. Phase 2 is where the moat starts.

---

## When the moat actually starts mattering

Per-tenant LoRA training only pays off when:

1. You have enough approved creatives per tenant to train on (~30 minimum, ~100 ideal)
2. The tenant uses you frequently enough that the LoRA refresh schedule (weekly?) gives a noticeable lift each campaign
3. The tenant cares more about "this looks like us" than "this looks great generally"

Until those three hold for at least one tenant, you're building infrastructure on a hypothesis.

---

## Decision framework

Answer these in order:

1. **Are you bottlenecked on raw image quality?**
   - No → don't switch yet. Most of your iterations have been about prompt engineering and layout, not the underlying model. Switching models doesn't fix prompt problems.
   - Yes → go to question 2.

2. **Will any specific paying customer materially uplift you if you self-host?**
   - No → don't switch yet. Build the customer first.
   - Yes — name them, get them to verbally commit to a price → go to question 3.

3. **Can you afford 5–6 weeks of focused engineering with no shipping in between?**
   - No → don't switch yet. Phase 1 alone gives you nothing customer-facing.
   - Yes → build Phase 1+2 together, do not stop at Phase 1.

---

## The cheap experiments to do before committing

Two experiments, both <$50 total, can validate the bet:

### Experiment 1 — Is Flux Schnell quality acceptable as a baseline?

Spin up Flux Schnell via Replicate API ($0.003/image), generate 10 creatives using your exact current prompts, compare side-by-side with Nano Banana Pro.

- **Pass:** Schnell is within 80% of Pro quality. LoRA can close the rest.
- **Fail:** Schnell looks meaningfully worse. Need Flux Dev ($0.025/image) or Flux Pro ($0.05/image) — recalculate cost model.

See `bench_flux_vs_gemini.py` in this repo for the script.

### Experiment 2 — Does LoRA actually move brand alignment?

Train one LoRA on Replicate using 10 of your tenant's approved creatives (~$5). Generate the same prompt with and without the LoRA. Have the tenant blind-vote which output is more on-brand.

- **Pass:** Tenant clearly prefers LoRA output. Moat thesis confirmed.
- **Fail:** No meaningful preference. Bottleneck isn't the model — it's something else (composition, copy, persona resolution).

---

## What we'd do as fallback if dedicated GPU fails

Resilience matters. The Gemini call in `backend/workers/creative.py` should stay wired up as a fallback. If self-hosted Flux endpoint is down or latency is too high, fall back to Gemini. Already conditional via `USE_FALLBACK = False` flag — we'd flip the condition.

---

## Verdict

**Don't switch today.** Run Experiment 1 this week (~30 min). Run Experiment 2 if Experiment 1 passes AND a specific tenant cares enough to invest 10 approved creatives. Build Phase 1+2 only if Experiment 2 passes AND a paying customer is on the line.

In the meantime, the wins are in prompt engineering, persona examples, and composition rules — all of which we've been working on. That's still where the bottleneck is.

---

## Triggers that flip the verdict to YES

- [ ] Cost: >2,000 images/month sustained for 4+ weeks
- [ ] Customer: named prospect commits to $X/mo if we self-host
- [ ] Compliance: regulated customer (healthcare, finance) blocked on Gemini data residency
- [ ] Competitive: a competitor launches per-tenant fine-tuning and customers ask about it

Revisit this doc when any trigger fires.
