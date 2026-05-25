"""
BELMONT OPS - TEMPLATE + SOP LIBRARY
Premium-voice email templates and internal SOPs.
All written in Jacob's direct, no-fluff voice. No em dashes.

Usage:
  /template — show menu
  /template followup_7day — specific template
  /sop — show menu
  /sop kickoff — specific SOP
"""

# ──────────────────────────────────────────────────────────────────────────
# CLIENT-FACING EMAIL TEMPLATES (Belmont brand voice)
# ──────────────────────────────────────────────────────────────────────────

TEMPLATES = {
    # ── COLD OUTREACH ────────────────────────────────────────────────────
    "outreach_homeowner": {
        "name": "Cold outreach — homeowner (general)",
        "body": """Hi [NAME],

Came across your project [SOURCE]. Belmont & Co. builds exactly this type of work in [LOCATION] — premium renovations and custom builds focused on craftsmanship.

Worth a quick 15-minute call this week to see if we're a fit? I can do [DAY 1] morning or [DAY 2] afternoon.

Jacob Cota
Belmont & Co. Fine Homes & Renovations
[PHONE] / [EMAIL]"""
    },

    "outreach_builder": {
        "name": "Cold outreach — builder partner",
        "body": """[NAME],

Jacob with Belmont & Co. in Red Deer. We focus on premium finish work, additions, and custom builds in Central Alberta. Strong on schedule, quality, and clean communication.

Looking to build a short list of trusted GC and trade relationships. Open to a 20-minute coffee or call this week?

Jacob Cota
[PHONE]"""
    },

    "outreach_deck": {
        "name": "Cold outreach — deck project",
        "body": """Hi [NAME],

Saw the post about your deck plans. We build a lot of composite and cedar decks in [LOCATION] — usually 600-1200 sqft, glass or aluminum railing, integrated lighting.

Happy to walk the site and give you a real number, not a phone guess. Free, no obligation.

When works this week?

Jacob Cota — Belmont & Co.
[PHONE]"""
    },

    # ── FOLLOW-UPS ───────────────────────────────────────────────────────
    "followup_3day": {
        "name": "Estimate follow-up (3 days, gentle)",
        "body": """Hi [NAME],

Wanted to make sure the estimate landed and you had a chance to look it over. Happy to walk through any line item or adjust scope if something doesn't fit.

If you're still gathering quotes, no rush. Just let me know what makes sense for you.

Jacob"""
    },

    "followup_7day": {
        "name": "Estimate follow-up (7 days, direct)",
        "body": """Hi [NAME],

Following up on the [PROJECT] estimate from last week.

If timing is the issue, we're booking [TIMEFRAME] now and that window will tighten quickly. If it's scope or budget, let's talk — there's usually a path forward.

What's your read on it?

Jacob"""
    },

    "followup_14day": {
        "name": "Estimate follow-up (14 days, final)",
        "body": """Hi [NAME],

Last check on the [PROJECT] proposal. If you've gone in a different direction that's completely fine — would just help me close the file on my end.

If you're still considering it, let's get on the phone this week. Pricing's only good through [DATE].

Jacob"""
    },

    # ── PROJECT COMMUNICATION ────────────────────────────────────────────
    "kickoff": {
        "name": "Project kickoff email",
        "body": """Hi [NAME],

Excited to get started on the [PROJECT]. Quick rundown of how we'll run this:

START DATE: [DATE]
SITE LEAD: Hunter Brewster — [PHONE]
COMMUNICATION: I'll send a brief written update every Friday with what shipped this week, what's next, and any decisions we need from you.

A few things we need from your side before Monday:
- [ITEM 1]
- [ITEM 2]
- [ITEM 3]

Any questions, text or call me direct. Looking forward to it.

Jacob"""
    },

    "weekly_update": {
        "name": "Weekly client update",
        "body": """[NAME] — quick week-in-review on [PROJECT]:

THIS WEEK:
- [SHIPPED ITEM 1]
- [SHIPPED ITEM 2]

NEXT WEEK:
- [PLANNED ITEM 1]
- [PLANNED ITEM 2]

NEEDED FROM YOU:
- [DECISION OR SELECTION] by [DATE]

On budget. On schedule. Reach out if questions.

Jacob"""
    },

    "delay_notice": {
        "name": "Delay notice (proactive)",
        "body": """Hi [NAME],

Heads up — [REASON FOR DELAY, e.g. tile arrived damaged from supplier, replacing now]. This pushes [AFFECTED MILESTONE] from [ORIG DATE] to [NEW DATE].

No impact to overall project cost. We're using the gap to [PRODUCTIVE WORKAROUND, e.g. get ahead on the millwork].

I'd rather tell you about issues right away than have them surprise you later. Any concerns let me know.

Jacob"""
    },

    "change_order": {
        "name": "Change order proposal",
        "body": """Hi [NAME],

Per our conversation about [SCOPE CHANGE], here's the formal change order.

ADDITIONAL SCOPE: [DESCRIPTION]
ADDITIONAL COST: $[AMOUNT] + GST
SCHEDULE IMPACT: [DAYS/NONE]
DEPOSIT TO START: [% or NONE]

Sign the attached and we'll fold it into the next milestone. Any questions, call me.

Jacob"""
    },

    "deposit_request": {
        "name": "Deposit request",
        "body": """Hi [NAME],

Contract signed — appreciate it. To lock in the [START DATE] start, we'll need the deposit of $[AMOUNT] + GST.

E-transfer to [EMAIL] (auto-deposit on, password not needed), or I can send a QBO invoice if preferred. Let me know which works.

Once that's in, we're locked.

Jacob"""
    },

    "late_payment_gentle": {
        "name": "Late payment (gentle, 7-14 days)",
        "body": """Hi [NAME],

Quick note — invoice [#] for $[AMOUNT] from [DATE] hasn't come through yet. Probably just got missed in the inbox.

Easy ways to settle: e-transfer to [EMAIL] or pay via the link on the invoice.

Let me know if there's any issue on your end.

Jacob"""
    },

    "late_payment_firm": {
        "name": "Late payment (firm, 30+ days)",
        "body": """[NAME],

Invoice [#] for $[AMOUNT] is now [X] days overdue. I need this settled by [DATE].

If there's a problem on your side I should know about, call me today. Otherwise please process payment by end of week.

Jacob
[PHONE]"""
    },

    "completion": {
        "name": "Project completion email",
        "body": """[NAME],

[PROJECT] is officially complete. Final walkthrough notes attached — all items signed off.

A few housekeeping items:
- Warranty: [WARRANTY TERMS]
- Maintenance: [ANY NOTES, e.g. composite deck cleaning, sealant refresh schedule]
- Final invoice: paid in full, statement attached.

It's been a pleasure working with you. If you have anyone in your network who'd benefit from what we do, an introduction is the highest compliment.

Jacob"""
    },

    "testimonial_request": {
        "name": "Testimonial request",
        "body": """Hi [NAME],

[PROJECT] turned out great — really happy with how the team executed and how you engaged through the process.

When you've got a minute, would you be willing to leave a short review on Google? Just being honest about your experience. It helps a lot when other Central Alberta homeowners are vetting builders.

Link: [GOOGLE REVIEW LINK]

Thanks for trusting us with the work.

Jacob"""
    },

    "referral_request": {
        "name": "Referral request",
        "body": """Hi [NAME],

Hope you're enjoying the [PROJECT] — heard good things from [SOURCE].

We grow mostly through introductions from clients who got what they paid for. If anyone in your network — neighbours, friends, family — is thinking about a reno, addition, or build, I'd love a warm intro.

No pressure. Just thought I'd ask.

Jacob"""
    },

    "decline_too_small": {
        "name": "Decline letter (project too small)",
        "body": """Hi [NAME],

Thanks for reaching out about the [PROJECT]. I appreciate you considering us.

Honest answer: this one isn't quite the right fit for Belmont's typical scope. We're set up for larger projects — generally $25K+ renovations and additions — which lets us deliver the quality and crew commitment our clients expect.

For what you're after, I'd suggest [ALT RECOMMENDATION e.g. a handyman or smaller GC]. Happy to point you to a couple of names if useful.

Best of luck with it.

Jacob"""
    },

    "decline_scope_mismatch": {
        "name": "Decline letter (scope mismatch)",
        "body": """Hi [NAME],

Thanks for the project details. After thinking it through, I'm going to pass on this one.

[BRIEF HONEST REASON: e.g. the timeline conflicts with current commitments / the scope falls outside our specialty / pricing expectations are too far from market]

I'd rather be straight with you upfront than commit and underdeliver.

If your situation changes or another project comes up that's a better fit, I'm always open to a conversation.

Jacob"""
    },

    "site_visit": {
        "name": "Site visit confirmation",
        "body": """Hi [NAME],

Confirming the site visit for [PROJECT] on [DATE] at [TIME].

I'll be at [ADDRESS]. Should take 30-45 minutes. I'll bring measuring tools and look at scope, structural details, and access.

After the visit I'll have a clearer estimate to you within [TIMEFRAME].

See you then.

Jacob"""
    },
}


# ──────────────────────────────────────────────────────────────────────────
# INTERNAL SOPs (Belmont operating procedures)
# ──────────────────────────────────────────────────────────────────────────

SOPS = {
    "new_lead": {
        "name": "New lead intake (speed-to-lead)",
        "body": """BELMONT NEW LEAD SOP

1. ACKNOWLEDGE (within 1 hour, ideally 15 min)
   - Text or email back: 'Got your message. Looking at it now. Call you in [X].'
   - Do NOT ghost. Speed-to-lead is the single biggest factor in close rate.

2. QUALIFY (call within 4 hours)
   Ask:
   - What are you trying to accomplish? (not just 'what do you want built')
   - Timeline driving the project?
   - Budget range you're working with?
   - Who else are you considering?
   - How did you hear about us?

3. SCORE (Belmont ICP)
   HOT: Central AB + budget $25K+ + decision-maker + timeline within 6mo
   WARM: Some signals met
   COOL: Budget unclear or location stretch
   COLD: Price-shopping, vague scope, outside service area

4. NEXT STEP
   HOT/WARM: Schedule site visit within 7 days
   COOL: Send 2-3 qualifying questions via email
   COLD: Polite decline letter, refer out if applicable

5. LOG
   - Add contact to JobTread
   - Note in Zep memory: source, score, key context
   - Set 3-day followup reminder if no response
"""
    },

    "site_visit": {
        "name": "Site visit checklist",
        "body": """BELMONT SITE VISIT SOP

BEFORE VISIT (24h prior):
- Confirm appointment via text
- Review any submitted photos or notes
- Check Google Earth for site context
- Bring: tape measure, laser, notepad, business cards, sample binder

ON-SITE (30-45 min):
- 5 min: introductions, walk inside, build rapport
- 15 min: walk the project area, measure, photograph
- 10 min: ask discovery questions:
  * What's working / not working about the current space?
  * What inspired the project?
  * Have you done renos before? Good or bad experiences?
  * Who lives here, how do you use the space?
  * Timeline expectations?
  * Budget range you're comfortable sharing?
- 10 min: walk them through Belmont's process, deliverables, what comes next
- 5 min: clear ask: 'I'll have an estimate to you by [DATE]. Sound good?'

AFTER VISIT (same day):
- Voice note all observations into Telegram (Belmont Ops agent will log)
- Photos uploaded to JobTread under the lead's record
- Site visit summary written within 24h

DELIVERABLE TIMELINE:
- Initial range: 2-3 business days
- Full line-item estimate: 5-7 business days
- Anything longer = update the client proactively
"""
    },

    "kickoff": {
        "name": "Project kickoff checklist",
        "body": """BELMONT PROJECT KICKOFF SOP

CONTRACT SIGNED:
- Deposit received and confirmed
- All scope changes captured in writing before start
- JobTread project created with full budget loaded

PRE-START (7 days before mobilization):
- Send kickoff email to client (use /template kickoff)
- Confirm permits (if applicable)
- Confirm material lead times — flag anything >3 weeks
- Confirm subcontractor schedule
- Confirm client selections (paint, tile, fixtures, etc.) deadlines

DAY 1 ON SITE:
- Site protection installed (floor covering, dust barriers, etc.)
- Crew briefed on scope and quality standards
- Photo: 'before' state from all key angles
- Note in JobTread: kickoff complete

WEEK 1:
- Daily photos uploaded to JobTread
- First Friday client update sent
- Any scope question or change captured immediately (not 'we'll deal with it later')

NO START ON SITE WITHOUT:
- Signed contract
- Deposit cleared
- Client selections locked or deadline set
"""
    },

    "weekly_jobsite": {
        "name": "Weekly jobsite walkthrough checklist",
        "body": """BELMONT WEEKLY JOBSITE WALKTHROUGH SOP

EVERY FRIDAY ON EVERY ACTIVE JOB:

SAFETY:
- PPE in use by all crew
- Site clean — no trip hazards, debris managed
- Tool/material storage organized

QUALITY:
- Spot check this week's work — does it meet Belmont standard?
- Walk through with site lead, note any rework needed
- Are subs delivering as agreed?

PROGRESS:
- Compare actual vs schedule — on track, ahead, behind?
- Update JobTread with completed milestones
- Flag risk items 7+ days before they become problems

BUDGET:
- Run budget vs actual report (use /jobs then /budget [job name])
- Any line item over 90% spent gets flagged
- Change orders captured this week — all signed?

CLIENT:
- Friday update written and sent (use /template weekly_update)
- Any client questions outstanding from earlier in week?

CREW:
- Pay confirmations / sub invoices for the week
- Anyone scheduled next week needs confirming
"""
    },

    "change_order": {
        "name": "Change order workflow",
        "body": """BELMONT CHANGE ORDER SOP

NO EXTRA WORK STARTS WITHOUT A SIGNED CHANGE ORDER.
Scope creep without paperwork = margin loss = unacceptable.

TRIGGER:
- Client asks for something not in original scope, OR
- Site condition discovered that requires unplanned work, OR
- Material substitution requested

PROCESS (same day):
1. Stop or do not start the extra work
2. Capture the change request in writing (email/text from client confirming what they want)
3. Price the change:
   - Materials + markup
   - Labour hours + rate
   - Sub costs + markup
   - Schedule impact in days
   - Minimum margin protected
4. Send change order document (use /template change_order)
5. Get signed before any work begins
6. Log in JobTread under the project
7. Adjust schedule and budget in JobTread

EXCEPTIONS: Emergency safety work happens first, paperwork follows within 24h.
"""
    },

    "completion": {
        "name": "Project completion checklist",
        "body": """BELMONT PROJECT COMPLETION SOP

PRE-FINAL WALKTHROUGH:
- All trades complete
- Final cleaning done
- Photo: 'after' state from same angles as 'before'
- Any deficiencies fixed before client sees it

FINAL WALKTHROUGH (with client):
- Walk every area, point out details and craftsmanship
- Note any minor punch list items (and commit to dates for fix)
- Hand over: keys, manuals, warranty documents, paint colour list, supplier names
- Take photos with client (for marketing, with permission)

ADMINISTRATIVE:
- Final invoice issued
- Final payment terms confirmed (cleared funds before warranty period starts)
- JobTread project marked complete with completion notes
- Lessons learned captured (use /lesson)

FOLLOW-UP (1 week after completion):
- Send completion email (use /template completion)
- Set 90-day check-in reminder
- Ask for testimonial (use /template testimonial_request)
- Ask for referral (use /template referral_request) — only after Google review left

POST-MORTEM (internal, within 7 days):
- Actual vs budget — what was the real margin?
- What broke, what worked?
- Lessons logged
"""
    },

    "estimate": {
        "name": "Estimate creation checklist",
        "body": """BELMONT ESTIMATE CREATION SOP

NO ESTIMATE GOES OUT WITHOUT:

1. CLEAR SCOPE
   - Specific enough to prevent disputes
   - Inclusions and exclusions explicit
   - Client responsibilities listed (permits, selections, access)

2. LINE-ITEM BREAKDOWN
   - Labour separate from materials
   - Sub trades itemized
   - Tier/spec level chosen and noted

3. MARGIN PROTECTION
   - Minimum 30% gross on renovations
   - Minimum 25% gross on additions/custom
   - If math says less, raise the price or pass on the job

4. CONTINGENCY
   - 10% minimum on renovations
   - 15% on additions/custom
   - Material escalation buffer 5% if job >90 days

5. PAYMENT MILESTONES
   - Tied to measurable progress (rough-in complete, drywall complete, etc.)
   - NOT calendar dates

6. GST APPLIED CORRECTLY
   - 5% in Alberta, no PST
   - Calculated on subtotal AFTER contingency

7. EXPIRY DATE
   - 14 days standard
   - Stated explicitly on the document

8. NEXT STEPS CLEAR
   - How to accept, how to ask questions
   - What happens after acceptance
"""
    },

    "quarterly_review": {
        "name": "Quarterly business review SOP",
        "body": """BELMONT QUARTERLY BUSINESS REVIEW SOP

RUN EVERY 90 DAYS. 90 MINUTES, NO INTERRUPTIONS.

PART 1 — NUMBERS (30 min):
- Revenue: actual vs target
- Gross margin: actual vs target (30%+ renos, 25%+ additions)
- Pipeline value at start vs end of quarter
- Close rate (estimates signed / estimates sent)
- AR aging — anything 60+ days?
- P&L review
- Net income trend toward $8K/month exit target

PART 2 — JOBS (20 min):
- Every active job: on track / ahead / behind
- Any margin compression — where and why?
- Any client relationship issues
- Subcontractor performance review

PART 3 — LEAD GEN (20 min):
- Where are leads coming from? (website, referral, ads, cold)
- Lead -> site visit conversion rate
- Site visit -> estimate conversion
- Estimate -> signed contract conversion
- What channel is producing highest-quality leads?

PART 4 — STRATEGY (15 min):
- What's the one bottleneck this quarter?
- What's the one thing that would 10x next quarter?
- Are non-negotiables holding (minimum margin, scope discipline, change order rule)?
- TopTick exit timeline — closer or further than 90 days ago?

PART 5 — WRITTEN OUTPUT (5 min):
- One paragraph summary
- Three priorities for next quarter
- Logged with /decision for the agent to recall
"""
    },
}


def list_templates() -> str:
    """Return a menu of all available templates."""
    lines = ["<b>Belmont Email Templates</b>\n"]
    lines.append("Use: <code>/template [key]</code>\n")
    for key, t in TEMPLATES.items():
        lines.append(f"  <code>{key}</code> — {t['name']}")
    return "\n".join(lines)


def get_template(key: str) -> str:
    """Return a specific template or a not-found message."""
    t = TEMPLATES.get(key.lower().strip())
    if not t:
        # Try partial match
        for k, v in TEMPLATES.items():
            if key.lower().strip() in k:
                t = v
                break
    if not t:
        return f"Template '{key}' not found. Send /template for the menu."
    return f"<b>{t['name']}</b>\n\n<pre>{t['body']}</pre>\n\n<i>Copy-paste and fill in the brackets.</i>"


def list_sops() -> str:
    """Return a menu of all available SOPs."""
    lines = ["<b>Belmont SOPs (Standard Operating Procedures)</b>\n"]
    lines.append("Use: <code>/sop [key]</code>\n")
    for key, s in SOPS.items():
        lines.append(f"  <code>{key}</code> — {s['name']}")
    return "\n".join(lines)


def get_sop(key: str) -> str:
    """Return a specific SOP or a not-found message."""
    s = SOPS.get(key.lower().strip())
    if not s:
        for k, v in SOPS.items():
            if key.lower().strip() in k:
                s = v
                break
    if not s:
        return f"SOP '{key}' not found. Send /sop for the menu."
    return f"<b>{s['name']}</b>\n\n<pre>{s['body']}</pre>"


# ──────────────────────────────────────────────────────────────────────────
# PRICING REFERENCE CARD (Central Alberta 2026)
# ──────────────────────────────────────────────────────────────────────────

PRICING = {
    "deck_pt": ("Pressure-treated deck", "$35-70/sqft", "no railing to aluminum"),
    "deck_composite": ("Composite deck", "$85-145/sqft", "aluminum to glass railing"),
    "deck_demo": ("Deck demo + disposal", "$8-14/sqft", ""),
    "pile_helical": ("Helical pile foundation", "$450-650/each", "typ 1 per 50-80 sqft deck"),
    "pergola": ("Pergola/cover add-on", "$25-40/sqft", "of covered area"),
    "bath_powder": ("Powder room refresh", "$8K-14K", ""),
    "bath_full": ("Full bathroom (50-70sqft, mid)", "$28K-42K", ""),
    "bath_premium": ("Full bathroom (70-100sqft, high)", "$45K-72K", "curbless, heated floor"),
    "bath_primary": ("Primary ensuite (100-160sqft)", "$65K-110K", "premium spec"),
    "kitchen_refresh": ("Cosmetic kitchen refresh", "$15K-28K", "paint, hardware, counters"),
    "kitchen_mid": ("Mid-spec kitchen reno", "$55K-95K", "stock+semi-custom cabs"),
    "kitchen_high": ("High-spec kitchen reno", "$110K-180K", "custom cabs, premium appliance"),
    "kitchen_premium": ("Premium chef kitchen", "$200K-350K+", "Wolf/Sub-Zero, custom millwork"),
    "addition_1s": ("Single-storey addition", "$475-725/sqft", "standard to premium finish"),
    "addition_2s": ("Two-storey addition", "$425-675/sqft", "standard to premium"),
    "garage_suite": ("Garage suite (over detached)", "$385-475/sqft", ""),
    "basement": ("Basement development", "$115-175/sqft", ""),
    "custom_prod": ("Custom home — production spec", "$310-380/sqft", "above grade"),
    "custom_mid": ("Custom home — mid-spec", "$385-475/sqft", "above grade"),
    "custom_high": ("Custom home — high-spec", "$475-625/sqft", "above grade"),
    "custom_lux": ("Custom home — luxury", "$625-900/sqft", "above grade"),
    "labour_lead": ("Lead carpenter labour", "$85-95/hr", "fully-loaded"),
    "labour_carp": ("Carpenter labour", "$65-75/hr", "fully-loaded"),
    "labour_help": ("Apprentice/helper labour", "$40-50/hr", "fully-loaded"),
    "sub_plumber": ("Plumber sub rate", "$145-175/hr", "or fixed bid"),
    "sub_electrician": ("Electrician sub rate", "$130-160/hr", "or fixed bid"),
    "sub_drywall": ("Drywall sub (hung/taped/primed)", "$2.80-3.50/sqft", ""),
    "sub_tile": ("Tile setter install", "$14-22/sqft", "installation only"),
    "permit": ("Building permit (Red Deer)", "0.7-1.2% of project", "min ~$280"),
    "engineering": ("Structural engineering", "$1,800-4,500", "typical residential"),
}


def list_pricing() -> str:
    """Return formatted pricing reference card."""
    lines = ["<b>Belmont Pricing Reference (Central AB, 2026)</b>\n"]
    lines.append("Use: <code>/pricing [key]</code> for specific, or all below:\n")
    sections = {
        "DECKS": ["deck_pt", "deck_composite", "deck_demo", "pile_helical", "pergola"],
        "BATHS": ["bath_powder", "bath_full", "bath_premium", "bath_primary"],
        "KITCHENS": ["kitchen_refresh", "kitchen_mid", "kitchen_high", "kitchen_premium"],
        "ADDITIONS": ["addition_1s", "addition_2s", "garage_suite", "basement"],
        "CUSTOM HOMES": ["custom_prod", "custom_mid", "custom_high", "custom_lux"],
        "LABOUR": ["labour_lead", "labour_carp", "labour_help"],
        "SUBS": ["sub_plumber", "sub_electrician", "sub_drywall", "sub_tile"],
        "SOFT": ["permit", "engineering"]
    }
    for section, keys in sections.items():
        lines.append(f"\n<b>{section}</b>")
        for k in keys:
            if k in PRICING:
                name, rate, note = PRICING[k]
                line = f"  <code>{k}</code>: {name} — <b>{rate}</b>"
                if note:
                    line += f" ({note})"
                lines.append(line)
    lines.append("\n<i>For a full estimate use /quote [description].</i>")
    return "\n".join(lines)


def get_pricing(key: str) -> str:
    """Return a specific pricing item."""
    k = key.lower().strip()
    p = PRICING.get(k)
    if not p:
        for pk, pv in PRICING.items():
            if k in pk:
                p = pv
                break
    if not p:
        return f"Pricing key '{key}' not found. Send /pricing for the menu."
    name, rate, note = p
    msg = f"<b>{name}</b>\n\nRate: <b>{rate}</b>"
    if note:
        msg += f"\nNote: {note}"
    msg += "\n\nApply 5% GST on top. Add contingency (10% renos, 15% additions/custom)."
    return msg
